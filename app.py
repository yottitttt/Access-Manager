from flask import Flask,session,render_template,request,redirect,flash,url_for,jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin,LoginManager,login_user,logout_user,login_required,current_user

from PIL import Image, ExifTags
from werkzeug.security import generate_password_hash,check_password_hash
import os

from datetime import datetime,timedelta
import pytz
jst = pytz.timezone('Asia/Tokyo')

from sqlalchemy.sql import func

app=Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI']='sqlite:///database.db'
app.config['SECRET_KEY']=os.urandom(24)
db=SQLAlchemy(app)

login_manager=LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# デフォルトのログインメッセージを無効にする
login_manager.login_message = None

class User(UserMixin,db.Model):
    id=db.Column(db.Integer,primary_key=True)
    username=db.Column(db.String(30),nullable=False,unique=True)
    password=db.Column(db.String(12),nullable=False)
    status=db.Column(db.String(3),default='退室中')
    image=db.Column(db.String(256), nullable=False, default='static/images/default.jpg')

class UserLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    check_in_time = db.Column(db.DateTime)
    check_out_time = db.Column(db.DateTime)
    duration = db.Column(db.Interval)
    month_year = db.Column(db.String(7), default=datetime.now().strftime("%Y-%m"))

    user = db.relationship('User', backref=db.backref('logs', lazy=True))

with app.app_context():
    db.create_all()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def get_monthly_totals(first_day_month,last_day_month):
    # 先月のデータを取得
    user_logs = UserLog.query.filter(UserLog.check_in_time >= first_day_month, UserLog.check_in_time <= last_day_month).all()
    
    # 全ユーザーを取得
    users = User.query.all()

    # 全ユーザーのIDを使ってuser_durationsを初期化
    user_durations = {user.id: timedelta() for user in users}

    # ユーザーごとの合計勤務時間を計算
    for log in user_logs:
        if log.duration:
            user_durations[log.user_id] += log.duration
                
    # 合計勤務時間が多い順にユーザーを並べ替え
    top_users = sorted(user_durations.items(), key=lambda x: x[1], reverse=True)
    
    # ユーザー情報と合計勤務時間を取得
    top_users_info = []
    for user_id, duration in top_users:
        user = User.query.get(user_id)
        if user:
            hours, remainder = divmod(duration.total_seconds(), 3600)
            minutes, seconds = divmod(remainder, 60)
            formatted_duration = f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"
            top_users_info.append({
                'username': user.username,
                'duration': formatted_duration
            })
    return top_users_info

def triming():
    with Image.open('static/images/'+str(current_user.id)+'profile.jpg') as img:
                # EXIF情報から画像の向きを取得
                for orientation in ExifTags.TAGS.keys():
                    if ExifTags.TAGS[orientation] == 'Orientation':
                        break
                
                exif = img._getexif()
                
                if exif is not None and orientation in exif:
                    if exif[orientation] == 3:
                        img = img.rotate(180, expand=True)
                    elif exif[orientation] == 6:
                        img = img.rotate(270, expand=True)
                    elif exif[orientation] == 8:
                        img = img.rotate(90, expand=True)
                # 画像の中心を計算
                center_x, center_y = img.width // 2, img.height // 2
                if img.width>img.height :
                    left = center_x - center_y
                    right = center_x + center_y

                    upper = 0
                    lower = img.height
                else :
                    left = center_y - center_x
                    right = center_y + center_x

                    upper = 0
                    lower = img.width

                # 画像をトリミング
                trimmed_img = img.crop((left, upper, right, lower))
                
                # トリミングした画像を保存
                trimmed_img.save(os.path.join('./static/images',str(current_user.id)+'profile.jpg' ))

@app.route('/',methods=['GET','POST'])
def index():
    return redirect('/base') 

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        username=request.form.get('username')
        password=request.form.get('password')

        user=User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect('/base')
        else:
            flash('名前，もしくはパスワードが間違っています．', 'danger')
    return render_template('login.html')
    
@app.route('/signup',methods=['GET','POST'])
def register():
    if request.method=='POST':
        username=request.form.get('username')
        password=request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user:
            flash('その名前は既に使われています．別の名前を使用してください．', 'danger')
            return render_template('signup.html')
        
        new_user=User(username=username,password=generate_password_hash(password,method='pbkdf2:sha256'))
        db.session.add(new_user)
        db.session.commit()
        return redirect('/login')
    return render_template('signup.html')
    
@app.route('/base',methods=['GET','POST'])
@login_required
def base():
    now = datetime.now()
    now = now.strftime('%Y-%m-%d %H:%M:%S')
    users = User.query.all()
    return render_template('base.html', users=users, now=now)

@app.route('/check_in', methods=['POST'])
@login_required
def check_in():
    now = datetime.now()
    user_log = UserLog(user_id=current_user.id, check_in_time=now, month_year=now.strftime('%Y-%m'))
    current_user.status = '入室中'
    db.session.add(user_log)
    db.session.commit()
    return redirect('/base')

@app.route('/check_out', methods=['POST'])
@login_required
def check_out():
    now = datetime.now()
    user_log = UserLog.query.filter_by(user_id=current_user.id, check_out_time=None).first()
    if user_log:
        if now.day - user_log.check_in_time.day>0:
            user_log.check_out_time = datetime(year=user_log.check_in_time.year,month=user_log.check_in_time.month,day=user_log.check_in_time.day,hour=23,minute=59,second=59)
            user_log.duration =user_log.check_out_time- user_log.check_in_time
        else:
            user_log.check_out_time = now
            user_log.duration = now - user_log.check_in_time
        
        current_user.status = '退室中'
        db.session.commit()
    return redirect('/base')

@app.route('/ranking')
@login_required
def ranking():
    # 現在の日付を取得
    now = datetime.now()

    # 次の月の最初の日を計算
    if now.month == 12:
        first_day_of_next_month = datetime(now.year + 1, 1, 1)
    else:
        first_day_of_next_month = datetime(now.year, now.month + 1, 1)

    # 現在の月の最終日を計算
    last_day_this_month = first_day_of_next_month - timedelta(days=1)
    first_day_this_month = datetime(now.year, now.month, 1)
    # 先月の初日と最終日を計算
    last_day_last_month = first_day_this_month - timedelta(days=1)
    first_day_last_month = datetime(last_day_last_month.year, last_day_last_month.month, 1)
    
    last_top_users=get_monthly_totals(first_day_last_month,last_day_last_month)
    this_top_users=get_monthly_totals(first_day_this_month,last_day_this_month)

    return render_template('ranking.html', last_top_users=last_top_users, this_top_users=this_top_users)

@app.route('/get_ranking/<string:month_year>')
@login_required
def get_ranking(month_year):
    first_day = datetime.strptime(month_year, "%Y-%m")
    last_day = (first_day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    
    rankings = get_monthly_totals(first_day, last_day)
    
    return jsonify(rankings)

@app.route('/profile/<int:user_id>',methods=['GET'])
@login_required
def profile(user_id):
    user = User.query.get(user_id)

    # 現在の日付を取得
    now = datetime.now()

    # 次の月の最初の日を計算
    if now.month == 12:
        first_day_of_next_month = datetime(now.year + 1, 1, 1)
    else:
        first_day_of_next_month = datetime(now.year, now.month + 1, 1)

    # 現在の月の最終日を計算
    last_day_this_month = first_day_of_next_month - timedelta(days=1)
    first_day_this_month = datetime(now.year, now.month, 1)

    this_logs = UserLog.query.filter(UserLog.user_id == user.id, 
                                     UserLog.check_in_time >= first_day_this_month,
                                     UserLog.check_in_time <= last_day_this_month).all()
    total_duration = timedelta()
    for log in this_logs:
        if log.duration:
            total_duration += log.duration
    
    hours, remainder = divmod(total_duration.total_seconds(), 3600)
    minutes, seconds = divmod(remainder, 60)
    formatted_duration = f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"

    userlogs = user.logs
    # 最新のログが先頭にくるようにソート
    userlogs = sorted(userlogs, key=lambda x: x.check_in_time, reverse=True) 
    formatted_userlogs = []
    count = 0
    for userlog in userlogs:
        # duration を時間、分、秒に変換
        if userlog.duration:
            total_seconds = int(userlog.duration.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)

        formatted_log = {
            'check_in_time': userlog.check_in_time.strftime('%Y-%m-%d %H:%M:%S'),
            'check_out_time': userlog.check_out_time.strftime('%Y-%m-%d %H:%M:%S') if userlog.check_out_time else '-',
            'duration': f"{hours:02}:{minutes:02}:{seconds:02}" if userlog.duration else '-'
        }
        formatted_userlogs.append(formatted_log)
        count += 1
        if count == 25:
            break

    
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    
    return render_template('profile.html', user=user, userlogs=formatted_userlogs, total_duration=formatted_duration, now=now_str)

@app.route('/get_events')
@login_required
def get_events():
    user_logs = UserLog.query.filter_by(user_id=current_user.id).all()
    events = []
    for log in user_logs:
        if log.check_in_time:
            events.append({
                'title': '入室',
                'start': log.check_in_time.isoformat(),
                'color': 'red' 
            })
        if log.check_out_time:
            events.append({
                'title': '退室',
                'start': log.check_out_time.isoformat(),
                'color': 'blue'
            })
    return jsonify(events)

@app.route('/change',methods=['GET','POST'])
@login_required
def change():
    if request.method=='POST':

        if request.form.get('username') and request.form.get('password')=='':
            flash('名前とパスワードが空白です．', 'danger')
            return render_template('change.html')
        elif request.form.get('username')=='':
            flash('名前が空白です．', 'danger')
            return render_template('change.html')
        elif request.form.get('password')=='':
            flash('パスワードが空白です．', 'danger')
            return render_template('change.html')
        if current_user.username!=request.form.get('username'):
            user = User.query.filter_by(username=request.form.get('username')).first()
            if user:
                flash('その名前は既に使われています．別の名前を使用してください．', 'danger')
                return render_template('change.html')      

        post=User.query.get(current_user.id)
        post.username=request.form.get('username')
        pass1=request.form.get('password')
        post.password=generate_password_hash(pass1,method='pbkdf2:sha256')

        file = request.files['profile_pic']
        if file.filename!='':
            if file.filename.lower().endswith(('.png')):
                file.save(os.path.join('./static/images', str(current_user.id)+'profile.png'))
                Image.open('static/images/'+str(current_user.id)+'profile.png').convert('RGB').save('static/images/'+str(current_user.id)+'profile.jpg')
            else:
                file.save(os.path.join('./static/images', str(current_user.id)+'profile.jpg'))

        triming()
        
        post.image='static/images/'+str(current_user.id)+'profile.jpg'
        db.session.commit()
        return redirect(url_for('profile', user_id=current_user.id))
    return render_template('change.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')


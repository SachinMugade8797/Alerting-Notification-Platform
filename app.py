from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///simple_alerts.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Database Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    last_login = db.Column(db.DateTime, default=datetime.utcnow)

class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    users = db.relationship('User', backref='team', lazy=True)

class Alert(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    severity = db.Column(db.String(20), nullable=False, default='Info')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    reminders_enabled = db.Column(db.Boolean, default=True)
    visibility_type = db.Column(db.String(20), nullable=False)
    target_team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    def get_read_count(self):
        return UserAlertStatus.query.filter_by(alert_id=self.id, is_read=True).count()
    
    def get_total_users(self):
        if self.visibility_type == 'org':
            return User.query.filter_by(is_admin=False).count()
        elif self.visibility_type == 'team':
            return User.query.filter_by(team_id=self.target_team_id).count()
        elif self.visibility_type == 'user':
            return 1
        return 0

class UserAlertStatus(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    alert_id = db.Column(db.Integer, db.ForeignKey('alert.id'), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    is_snoozed = db.Column(db.Boolean, default=False)
    snooze_until = db.Column(db.DateTime, nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)
    
    user = db.relationship('User', backref='alert_statuses')
    alert = db.relationship('Alert', backref='user_statuses')

# Routes
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/admin')
def admin_dashboard():
    alerts = Alert.query.filter_by(is_active=True).all()
    alert_data = []
    for alert in alerts:
        read_count = alert.get_read_count()
        total_users = alert.get_total_users()
        read_percentage = round((read_count / total_users * 100) if total_users > 0 else 0, 1)
        alert_data.append({
            'alert': alert,
            'read_count': read_count,
            'total_users': total_users,
            'read_percentage': read_percentage
        })
    return render_template('admin_dashboard.html', alert_data=alert_data)

@app.route('/admin/create-alert', methods=['GET', 'POST'])
def create_alert():
    if request.method == 'POST':
        title = request.form['title']
        message = request.form['message']
        severity = request.form['severity']
        visibility_type = request.form['visibility_type']
        reminders_enabled = 'reminders_enabled' in request.form
        
        alert = Alert(
            title=title,
            message=message,
            severity=severity,
            visibility_type=visibility_type,
            reminders_enabled=reminders_enabled,
            created_by=1
        )
        
        if visibility_type == 'team':
            alert.target_team_id = request.form.get('target_team_id')
        elif visibility_type == 'user':
            alert.target_user_id = request.form.get('target_user_id')
        
        db.session.add(alert)
        db.session.commit()
        
        flash('Alert created successfully!', 'success')
        return redirect(url_for('admin_dashboard'))
    
    teams = Team.query.all()
    users = User.query.filter_by(is_admin=False).all()
    return render_template('create_alert.html', teams=teams, users=users)

@app.route('/dashboard/<int:user_id>')
def user_dashboard(user_id):
    user = User.query.get_or_404(user_id)
    user.last_login = datetime.utcnow()
    db.session.commit()
    
    visible_alerts = get_user_alerts(user)
    
    # Check for new alerts (last 5 minutes for demo)
    new_alerts = []
    for alert in visible_alerts:
        if alert.created_at > (datetime.utcnow() - timedelta(minutes=5)):
            # Convert alert object to dictionary for JSON
            new_alerts.append({
                'id': alert.id,
                'title': alert.title,
                'message': alert.message,
                'severity': alert.severity,
                'created_at': alert.created_at.strftime('%Y-%m-%d %H:%M')
            })
    
    return render_template('user_dashboard.html', user=user, alerts=visible_alerts, new_alerts=new_alerts)

@app.route('/api/mark-read', methods=['POST'])
def mark_read():
    try:
        data = request.json
        user_id = data.get('user_id')
        alert_id = data.get('alert_id')
        
        status = UserAlertStatus.query.filter_by(user_id=user_id, alert_id=alert_id).first()
        if not status:
            status = UserAlertStatus(user_id=user_id, alert_id=alert_id)
            db.session.add(status)
        
        status.is_read = True
        status.read_at = datetime.utcnow()
        db.session.commit()
        
        alert = Alert.query.get(alert_id)
        return jsonify({
            'success': True, 
            'message': f'✅ "{alert.title}" marked as read!'
        })
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500

@app.route('/api/snooze-alert', methods=['POST'])
def snooze_alert():
    try:
        data = request.json
        user_id = data.get('user_id')
        alert_id = data.get('alert_id')
        
        status = UserAlertStatus.query.filter_by(user_id=user_id, alert_id=alert_id).first()
        if not status:
            status = UserAlertStatus(user_id=user_id, alert_id=alert_id)
            db.session.add(status)
        
        status.is_snoozed = True
        status.snooze_until = datetime.now().replace(hour=23, minute=59, second=59)
        db.session.commit()
        
        alert = Alert.query.get(alert_id)
        return jsonify({
            'success': True, 
            'message': f'😴 "{alert.title}" snoozed until tomorrow!'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500

@app.route('/api/toggle-reminder/<int:alert_id>', methods=['POST'])
def toggle_reminder(alert_id):
    try:
        alert = Alert.query.get_or_404(alert_id)
        alert.reminders_enabled = not alert.reminders_enabled
        db.session.commit()
        
        status = "enabled" if alert.reminders_enabled else "disabled"
        return jsonify({
            'success': True,
            'message': f'🔔 Reminders {status} for "{alert.title}"',
            'reminders_enabled': alert.reminders_enabled
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500

@app.route('/api/delete-alert/<int:alert_id>', methods=['POST'])
def delete_alert(alert_id):
    try:
        alert = Alert.query.get_or_404(alert_id)
        
        # Delete related user alert statuses first
        UserAlertStatus.query.filter_by(alert_id=alert_id).delete()
        
        # Delete the alert
        alert_title = alert.title
        db.session.delete(alert)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'🗑️ Alert "{alert_title}" deleted successfully!'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500

# Helper Functions
def get_user_alerts(user):
    alerts = []
    
    # Organization alerts
    org_alerts = Alert.query.filter_by(visibility_type='org', is_active=True).all()
    alerts.extend(org_alerts)
    
    # Team alerts
    if user.team_id:
        team_alerts = Alert.query.filter_by(visibility_type='team', target_team_id=user.team_id, is_active=True).all()
        alerts.extend(team_alerts)
    
    # User specific alerts
    user_alerts = Alert.query.filter_by(visibility_type='user', target_user_id=user.id, is_active=True).all()
    alerts.extend(user_alerts)
    
    return alerts

def create_sample_data():
    print("Creating sample data...")
    
    # Create teams
    engineering = Team(name='Engineering')
    marketing = Team(name='Marketing')
    db.session.add(engineering)
    db.session.add(marketing)
    db.session.commit()
    
    # Create users
    admin = User(name='Admin User', email='admin@company.com', is_admin=True)
    john = User(name='John Doe', email='john@company.com', team_id=engineering.id)
    jane = User(name='Jane Smith', email='jane@company.com', team_id=marketing.id)
    
    db.session.add(admin)
    db.session.add(john)
    db.session.add(jane)
    db.session.commit()
    
    # Create sample alert
    sample_alert = Alert(
        title='Welcome to Alert System!',
        message='This is your first alert. Try marking it as read or snoozing it.',
        severity='Info',
        visibility_type='org',
        reminders_enabled=True,
        created_by=admin.id
    )
    db.session.add(sample_alert)
    db.session.commit()
    
    print("✅ Sample data created!")

if __name__ == '__main__':
    with app.app_context():
        print("🚀 Starting Alert System...")
        db.create_all()
        
        if User.query.count() == 0:
            create_sample_data()
    
# this is made for run project while edit
    app.run(debug=True)

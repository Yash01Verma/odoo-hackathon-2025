from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///skillswap.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)
# Many-to-many: User <-> Skills Offered
user_skills_offered = db.Table('user_skills_offered',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('skill_id', db.Integer, db.ForeignKey('skills.id'), primary_key=True)
)

# Many-to-many: User <-> Skills Wanted
user_skills_wanted = db.Table('user_skills_wanted',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('skill_id', db.Integer, db.ForeignKey('skills.id'), primary_key=True)
)


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(100))
    profile_photo = db.Column(db.String(250))  # URL or file path
    availability = db.Column(db.String(100))  # e.g. "weekends, evenings"
    is_public = db.Column(db.Boolean, default=True)
    
    skills_offered = db.relationship('Skill', secondary=user_skills_offered, backref='offered_by')
    skills_wanted = db.relationship('Skill', secondary=user_skills_wanted, backref='wanted_by')
    
    sent_requests = db.relationship('SwapRequest', foreign_keys='SwapRequest.requester_id', backref='requester', lazy=True)
    received_requests = db.relationship('SwapRequest', foreign_keys='SwapRequest.receiver_id', backref='receiver', lazy=True)

class Skill(db.Model):
    __tablename__ = 'skills'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

class SwapRequest(db.Model):
    __tablename__ = 'swap_requests'
    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, accepted, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    rating = db.relationship('Rating', uselist=False, backref='swap_request')

class Rating(db.Model):
    __tablename__ = 'ratings'
    id = db.Column(db.Integer, primary_key=True)
    swap_request_id = db.Column(db.Integer, db.ForeignKey('swap_requests.id'), unique=True)
    score = db.Column(db.Integer)  # e.g. 1–5 stars
    feedback = db.Column(db.Text)

### HELPERS ###

def get_or_create_skill(name):
    skill = Skill.query.filter_by(name=name.lower()).first()
    if not skill:
        skill = Skill(name=name.lower())
        db.session.add(skill)
        db.session.commit()
    return skill

### ROUTES ###

@app.route('/users', methods=['POST'])
def create_user():
    data = request.json
    if not data or 'name' not in data:
        return jsonify({'error': 'Name is required'}), 400
    
    user = User(
        name=data['name'],
        location=data.get('location'),
        profile_photo=data.get('profile_photo'),
        availability=data.get('availability'),
        is_public=data.get('is_public', True)
    )
    
    for s in data.get('skills_offered', []):
        skill = get_or_create_skill(s)
        user.skills_offered.append(skill)
    
    for s in data.get('skills_wanted', []):
        skill = get_or_create_skill(s)
        user.skills_wanted.append(skill)
    
    db.session.add(user)
    db.session.commit()
    return jsonify({'message': 'User created', 'user_id': user.id}), 201

@app.route('/users/<int:user_id>', methods=['GET'])
def get_user(user_id):
    user = User.query.get_or_404(user_id)
    if not user.is_public:
        return jsonify({'error': 'Profile is private'}), 403
    
    return jsonify({
        'id': user.id,
        'name': user.name,
        'location': user.location,
        'profile_photo': user.profile_photo,
        'availability': user.availability,
        'is_public': user.is_public,
        'skills_offered': [s.name for s in user.skills_offered],
        'skills_wanted': [s.name for s in user.skills_wanted]
    })

@app.route('/search')
def search_users():
    skill_name = request.args.get('skill')
    if not skill_name:
        return jsonify({'error': 'Skill query param required'}), 400
    skill = Skill.query.filter_by(name=skill_name.lower()).first()
    if not skill:
        return jsonify({'results': []})
    
    users = [u for u in skill.offered_by if u.is_public]
    results = []
    for user in users:
        results.append({
            'id': user.id,
            'name': user.name,
            'location': user.location,
            'skills_offered': [s.name for s in user.skills_offered],
            'skills_wanted': [s.name for s in user.skills_wanted],
            'availability': user.availability
        })
    return jsonify({'results': results})

@app.route('/swap_requests', methods=['POST'])
def make_swap_request():
    data = request.json
    requester_id = data.get('requester_id')
    receiver_id = data.get('receiver_id')
    if not requester_id or not receiver_id:
        return jsonify({'error': 'Requester and Receiver IDs required'}), 400
    if requester_id == receiver_id:
        return jsonify({'error': 'Cannot request swap with yourself'}), 400
    
    existing = SwapRequest.query.filter_by(requester_id=requester_id, receiver_id=receiver_id, status='pending').first()
    if existing:
        return jsonify({'error': 'Swap request already pending'}), 400
    
    swap = SwapRequest(requester_id=requester_id, receiver_id=receiver_id)
    db.session.add(swap)
    db.session.commit()
    return jsonify({'message': 'Swap request sent', 'swap_id': swap.id}), 201

@app.route('/swap_requests/<int:swap_id>', methods=['PATCH'])
def update_swap_request(swap_id):
    data = request.json
    swap = SwapRequest.query.get_or_404(swap_id)
    action = data.get('action')
    if action not in ['accept', 'reject']:
        return jsonify({'error': 'Action must be accept or reject'}), 400
    if swap.status != 'pending':
        return jsonify({'error': 'Swap request already processed'}), 400
    
    swap.status = 'accepted' if action == 'accept' else 'rejected'
    db.session.commit()
    return jsonify({'message': f'Swap request {swap.status}'})

@app.route('/swap_requests/<int:swap_id>', methods=['DELETE'])
def delete_swap_request(swap_id):
    swap = SwapRequest.query.get_or_404(swap_id)
    if swap.status != 'pending':
        return jsonify({'error': 'Cannot delete processed swap requests'}), 400
    
    db.session.delete(swap)
    db.session.commit()
    return jsonify({'message': 'Swap request deleted'})

@app.route('/users/<int:user_id>/swap_requests')
def list_swap_requests(user_id):
    user = User.query.get_or_404(user_id)
    sent = [{'id': s.id, 'to': s.receiver.name, 'status': s.status, 'created_at': s.created_at.isoformat()} for s in user.sent_requests]
    received = [{'id': s.id, 'from': s.requester.name, 'status': s.status, 'created_at': s.created_at.isoformat()} for s in user.received_requests]
    return jsonify({'sent_requests': sent, 'received_requests': received})

@app.route('/swap_requests/<int:swap_id>/rating', methods=['POST'])
def add_rating(swap_id):
    swap = SwapRequest.query.get_or_404(swap_id)
    if swap.status != 'accepted':
        return jsonify({'error': 'Can only rate accepted swaps'}), 400
    if swap.rating:
        return jsonify({'error': 'Rating already exists'}), 400
    
    data = request.json
    score = data.get('score')
    feedback = data.get('feedback', '')
    if not score or not (1 <= score <= 5):
        return jsonify({'error': 'Score must be between 1 and 5'}), 400
    
    rating = Rating(swap_request_id=swap.id, score=score, feedback=feedback)
    db.session.add(rating)
    db.session.commit()
    return jsonify({'message': 'Rating added'})

if __name__ == '__main__':
    app.run(debug=True)


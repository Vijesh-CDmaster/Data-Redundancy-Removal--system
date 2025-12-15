from flask import Flask, render_template, request, jsonify
from datetime import datetime
import hashlib
import json
import re
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError

app = Flask(__name__)

# MongoDB Connection
MONGO_URI = "mongodb+srv://viju7122006:viju7122006@cluster0.y0xsnbk.mongodb.net/?appName=Cluster0"
client = MongoClient(MONGO_URI)
db = client['redundancy_system']
data_collection = db['entries']

# Create compound unique index on normalized email and phone
# This prevents duplicates at database level
data_collection.create_index([("normalized_email", ASCENDING)], unique=True, sparse=True)
data_collection.create_index([("normalized_phone", ASCENDING)], unique=True, sparse=True)
data_collection.create_index([("timestamp", ASCENDING)])

def normalize_email(email):
    """Normalize email: lowercase and trim whitespace"""
    if not email:
        return None
    return email.strip().lower()

def normalize_phone(phone):
    """Normalize phone: remove all non-digit characters except leading +"""
    if not phone:
        return None
    # Keep only digits and leading +
    cleaned = re.sub(r'[^\d+]', '', phone)
    # If it starts with +, keep it, otherwise just digits
    if cleaned.startswith('+'):
        return '+' + re.sub(r'\D', '', cleaned[1:])
    return re.sub(r'\D', '', cleaned)

def validate_email(email):
    """Validate email format"""
    if not email:
        return False
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return re.match(pattern, email.strip()) is not None

def validate_phone(phone):
    """Validate phone number format (10-15 digits)"""
    if not phone:
        return False
    normalized = normalize_phone(phone)
    # Check if it has 10-15 digits
    digit_count = len(re.sub(r'\D', '', normalized))
    return 10 <= digit_count <= 15

def sanitize_input(data):
    """Sanitize and trim all input fields"""
    sanitized = {}
    for key, value in data.items():
        if isinstance(value, str):
            sanitized[key] = value.strip()
        else:
            sanitized[key] = value
    return sanitized

def check_duplicate(email, phone):
    """
    Check if a record with the same email OR phone already exists.
    Returns the existing record if found, None otherwise.
    """
    normalized_email = normalize_email(email)
    normalized_phone = normalize_phone(phone)
    
    # Check for duplicate by email OR phone
    query = {
        '$or': [
            {'normalized_email': normalized_email} if normalized_email else {},
            {'normalized_phone': normalized_phone} if normalized_phone else {}
        ]
    }
    
    # Remove empty dictionaries from query
    query['$or'] = [q for q in query['$or'] if q]
    
    if not query['$or']:
        return None
    
    existing = data_collection.find_one(query)
    return existing

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/validate', methods=['POST'])
def validate_data():
    """
    BACKEND VALIDATION - Single source of truth
    Validates data and checks for duplicates
    Returns detailed status for frontend display
    """
    try:
        data = request.json
        errors = []
        
        # Sanitize inputs
        data = sanitize_input(data)
        
        # Check required fields
        if not data.get('name'):
            errors.append("Name is required")
        if not data.get('email'):
            errors.append("Email is required")
        if not data.get('phone'):
            errors.append("Phone number is required")
        
        # Validate email format
        if data.get('email') and not validate_email(data['email']):
            errors.append("Invalid email format")
        
        # Validate phone format
        if data.get('phone') and not validate_phone(data['phone']):
            errors.append("Invalid phone number format (10-15 digits required)")
        
        # Return validation errors if any
        if errors:
            return jsonify({
                'status': 'invalid',
                'valid': False,
                'errors': errors
            }), 400
        
        # Check for duplicates (BACKEND CHECK)
        existing = check_duplicate(data['email'], data['phone'])
        
        if existing:
            # Duplicate found - return existing record
            return jsonify({
                'status': 'duplicate',
                'valid': False,
                'message': 'A record with this email or phone number already exists',
                'duplicate_record': {
                    'id': existing['entry_id'],
                    'name': existing['data']['name'],
                    'email': existing['data']['email'],
                    'phone': existing['data']['phone'],
                    'timestamp': existing['timestamp'],
                    'verified': existing.get('verified', False)
                }
            }), 200
        
        # No duplicate - validation passed
        return jsonify({
            'status': 'unique',
            'valid': True,
            'message': 'Data is unique and valid. Ready to insert.'
        }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'valid': False,
            'errors': [f"Server error: {str(e)}"]
        }), 500

@app.route('/api/add', methods=['POST'])
def add_data():
    """
    ADD DATA - Backend controls insertion
    Only inserts if no duplicate exists
    Returns created or existing record
    """
    try:
        data = request.json
        errors = []
        
        # Sanitize inputs
        data = sanitize_input(data)
        
        # Validate required fields
        if not data.get('name'):
            errors.append("Name is required")
        if not data.get('email'):
            errors.append("Email is required")
        if not data.get('phone'):
            errors.append("Phone number is required")
        
        # Validate formats
        if data.get('email') and not validate_email(data['email']):
            errors.append("Invalid email format")
        if data.get('phone') and not validate_phone(data['phone']):
            errors.append("Invalid phone number format")
        
        if errors:
            return jsonify({
                'status': 'invalid',
                'success': False,
                'errors': errors
            }), 400
        
        # CRITICAL: Check for duplicates BEFORE inserting
        existing = check_duplicate(data['email'], data['phone'])
        
        if existing:
            # Duplicate exists - DO NOT INSERT
            # Return the existing record instead
            return jsonify({
                'status': 'duplicate',
                'success': False,
                'message': 'Record already exists. No new entry created.',
                'record': {
                    'id': existing['entry_id'],
                    'name': existing['data']['name'],
                    'email': existing['data']['email'],
                    'phone': existing['data']['phone'],
                    'address': existing['data'].get('address', ''),
                    'company': existing['data'].get('company', ''),
                    'timestamp': existing['timestamp'],
                    'verified': existing.get('verified', False)
                }
            }), 200
        
        # No duplicate - proceed with insertion
        normalized_email = normalize_email(data['email'])
        normalized_phone = normalize_phone(data['phone'])
        
        # Get next sequential ID
        last_entry = data_collection.find_one(sort=[("entry_id", -1)])
        next_id = (last_entry['entry_id'] + 1) if last_entry else 1
        
        # Create new entry
        entry = {
            'entry_id': next_id,
            'data': {
                'name': data['name'],
                'email': data['email'],
                'phone': data['phone'],
                'address': data.get('address', ''),
                'company': data.get('company', '')
            },
            'normalized_email': normalized_email,
            'normalized_phone': normalized_phone,
            'timestamp': datetime.utcnow().isoformat(),
            'verified': True  # Only backend sets this
        }
        
        # Insert into database
        result = data_collection.insert_one(entry)
        
        # Return the newly created record
        return jsonify({
            'status': 'created',
            'success': True,
            'message': 'New record created successfully',
            'record': {
                'id': entry['entry_id'],
                'name': entry['data']['name'],
                'email': entry['data']['email'],
                'phone': entry['data']['phone'],
                'address': entry['data'].get('address', ''),
                'company': entry['data'].get('company', ''),
                'timestamp': entry['timestamp'],
                'verified': entry['verified']
            }
        }), 201
        
    except DuplicateKeyError:
        # Database-level duplicate constraint triggered
        existing = check_duplicate(data['email'], data['phone'])
        return jsonify({
            'status': 'duplicate',
            'success': False,
            'message': 'Duplicate detected by database constraint',
            'record': {
                'id': existing['entry_id'] if existing else None,
                'verified': existing.get('verified', False) if existing else False
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'success': False,
            'errors': [f"Database error: {str(e)}"]
        }), 500

@app.route('/api/data', methods=['GET'])
def get_data():
    """Retrieve all stored data from MongoDB"""
    try:
        entries = list(data_collection.find().sort("timestamp", -1).limit(100))
        
        # Format response
        formatted_entries = []
        for entry in entries:
            formatted_entries.append({
                'id': entry['entry_id'],
                'name': entry['data']['name'],
                'email': entry['data']['email'],
                'phone': entry['data']['phone'],
                'address': entry['data'].get('address', ''),
                'company': entry['data'].get('company', ''),
                'timestamp': entry['timestamp'],
                'verified': entry.get('verified', False)
            })
        
        return jsonify({
            'count': len(formatted_entries),
            'data': formatted_entries
        })
    except Exception as e:
        return jsonify({
            'count': 0,
            'data': [],
            'error': str(e)
        })

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get database statistics"""
    try:
        total_entries = data_collection.count_documents({})
        verified_entries = data_collection.count_documents({'verified': True})
        
        return jsonify({
            'total_entries': total_entries,
            'unique_entries': verified_entries,
            'efficiency': f"{(verified_entries/max(total_entries, 1)*100):.1f}%"
        })
    except Exception as e:
        return jsonify({
            'total_entries': 0,
            'unique_entries': 0,
            'efficiency': '100%',
            'error': str(e)
        })

@app.route('/api/clear', methods=['POST'])
def clear_data():
    """Clear all data (testing only)"""
    try:
        result = data_collection.delete_many({})
        return jsonify({
            'success': True,
            'message': f'Database cleared. {result.deleted_count} entries removed.'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

if __name__ == '__main__':
    app.run(debug=True)
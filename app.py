from flask import Flask, render_template, request, jsonify
from datetime import datetime
import re
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError
import traceback

app = Flask(__name__)

# MongoDB Connection with timeout
MONGO_URI = "mongodb+srv://viju7122006:viju7122006@cluster0.y0xsnbk.mongodb.net/?appName=Cluster0"

try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    # Test connection
    client.admin.command('ping')
    print("✅ MongoDB connected successfully")
    
    db = client['redundancy_system']
    users_collection = db['users']
    
    # Create unique indexes on email and phone
    try:
        users_collection.create_index([("email", ASCENDING)], unique=True, sparse=True)
        users_collection.create_index([("phone", ASCENDING)], unique=True, sparse=True)
        print("✅ Unique indexes created successfully")
    except Exception as e:
        print(f"⚠️ Index creation: {e}")
        
except ServerSelectionTimeoutError as e:
    print(f"❌ MongoDB connection failed: {e}")
    print("⚠️ Make sure your IP is whitelisted in MongoDB Atlas")
    client = None
except Exception as e:
    print(f"❌ MongoDB error: {e}")
    client = None

# Track attempts for metrics
attempts_collection = db['attempts'] if client else None

def normalize_email(email):
    """Normalize email: lowercase + strip"""
    if not email:
        return None
    return email.strip().lower()

def normalize_phone(phone):
    """Normalize phone: digits only"""
    if not phone:
        return None
    return re.sub(r'\D', '', phone)

def normalize_name(name):
    """Normalize name: strip whitespace"""
    if not name:
        return None
    return name.strip()

def validate_email(email):
    """Validate email format"""
    if not email:
        return False
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return re.match(pattern, email.strip()) is not None

def validate_phone(phone):
    """Validate phone format (10-15 digits)"""
    if not phone:
        return False
    digits = re.sub(r'\D', '', phone)
    return 10 <= len(digits) <= 15

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/add', methods=['POST'])
def add_data():
    """
    MAIN ENDPOINT - Add data with duplicate prevention
    Backend is single source of truth
    """
    try:
        # Check MongoDB connection
        if not client:
            return jsonify({
                'status': 'error',
                'success': False,
                'errors': ['Database connection failed. Please check MongoDB Atlas configuration.']
            }), 500
        
        data = request.json
        print(f"📝 Received data: {data}")
        
        # Track attempt
        try:
            attempts_collection.insert_one({
                'timestamp': datetime.utcnow().isoformat(),
                'data': data
            })
        except Exception as e:
            print(f"⚠️ Failed to track attempt: {e}")
        
        # Normalize inputs
        normalized_email = normalize_email(data.get('email'))
        normalized_phone = normalize_phone(data.get('phone'))
        normalized_name = normalize_name(data.get('name'))
        
        print(f"✨ Normalized - Email: {normalized_email}, Phone: {normalized_phone}")
        
        # Validation
        errors = []
        if not normalized_name:
            errors.append("Name is required")
        if not normalized_email:
            errors.append("Email is required")
        elif not validate_email(normalized_email):
            errors.append("Invalid email format")
        if not normalized_phone:
            errors.append("Phone is required")
        elif not validate_phone(normalized_phone):
            errors.append("Invalid phone format (10-15 digits required)")
        
        if errors:
            print(f"❌ Validation errors: {errors}")
            return jsonify({
                'status': 'invalid',
                'success': False,
                'errors': errors
            }), 400
        
        # Check for duplicate using MongoDB query
        print(f"🔍 Checking for duplicates...")
        existing = users_collection.find_one({
            "$or": [
                {"email": normalized_email},
                {"phone": normalized_phone}
            ]
        })
        
        if existing:
            # DUPLICATE FOUND
            print(f"⚠️ Duplicate found: {existing.get('email')} / {existing.get('phone')}")
            return jsonify({
                'status': 'duplicate',
                'success': False,
                'message': 'A record with this email or phone already exists',
                'record': {
                    'id': str(existing['_id']),
                    'name': existing['name'],
                    'email': existing['email'],
                    'phone': existing['phone'],
                    'address': existing.get('address', ''),
                    'company': existing.get('company', ''),
                    'timestamp': existing['timestamp'],
                    'verified': existing.get('verified', False)
                }
            }), 200
        
        # NO DUPLICATE - Insert new record
        print(f"✅ No duplicate found. Inserting new record...")
        new_document = {
            'name': normalized_name,
            'email': normalized_email,
            'phone': normalized_phone,
            'address': data.get('address', '').strip(),
            'company': data.get('company', '').strip(),
            'timestamp': datetime.utcnow().isoformat(),
            'verified': True
        }
        
        try:
            result = users_collection.insert_one(new_document)
            inserted_id = str(result.inserted_id)
            print(f"✅ Record inserted successfully: {inserted_id}")
            
            return jsonify({
                'status': 'created',
                'success': True,
                'message': 'New record created successfully',
                'record': {
                    'id': inserted_id,
                    'name': new_document['name'],
                    'email': new_document['email'],
                    'phone': new_document['phone'],
                    'address': new_document['address'],
                    'company': new_document['company'],
                    'timestamp': new_document['timestamp'],
                    'verified': new_document['verified']
                }
            }), 201
            
        except DuplicateKeyError as e:
            print(f"⚠️ Database duplicate key error: {e}")
            # Fetch the actual existing document
            existing = users_collection.find_one({
                "$or": [
                    {"email": normalized_email},
                    {"phone": normalized_phone}
                ]
            })
            
            if existing:
                return jsonify({
                    'status': 'duplicate',
                    'success': False,
                    'message': 'Duplicate detected by database constraint',
                    'record': {
                        'id': str(existing['_id']),
                        'name': existing['name'],
                        'email': existing['email'],
                        'phone': existing['phone'],
                        'address': existing.get('address', ''),
                        'company': existing.get('company', ''),
                        'timestamp': existing['timestamp'],
                        'verified': existing.get('verified', False)
                    }
                }), 200
                
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"❌ Server error: {e}")
        print(f"Traceback: {error_trace}")
        return jsonify({
            'status': 'error',
            'success': False,
            'errors': [f"Server error: {str(e)}"]
        }), 500

@app.route('/api/data', methods=['GET'])
def get_data():
    """Retrieve all verified records from MongoDB"""
    try:
        if not client:
            return jsonify({
                'count': 0,
                'data': [],
                'error': 'Database not connected'
            })
            
        # Get only verified records
        records = list(users_collection.find({'verified': True}).sort("timestamp", -1).limit(100))
        
        formatted_records = []
        for record in records:
            formatted_records.append({
                'id': str(record['_id']),
                'name': record['name'],
                'email': record['email'],
                'phone': record['phone'],
                'address': record.get('address', ''),
                'company': record.get('company', ''),
                'timestamp': record['timestamp'],
                'verified': record.get('verified', False)
            })
        
        return jsonify({
            'count': len(formatted_records),
            'data': formatted_records
        })
    except Exception as e:
        print(f"❌ Error loading data: {e}")
        return jsonify({
            'count': 0,
            'data': [],
            'error': str(e)
        })

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """
    Get accurate statistics
    - Total attempts (all POST requests)
    - Unique entries (successful inserts)
    - Efficiency = (unique / attempts) * 100
    """
    try:
        if not client:
            return jsonify({
                'total_attempts': 0,
                'unique_entries': 0,
                'efficiency': '100%',
                'duplicates_prevented': 0,
                'error': 'Database not connected'
            })
            
        total_attempts = attempts_collection.count_documents({})
        unique_entries = users_collection.count_documents({'verified': True})
        
        if total_attempts == 0:
            efficiency = 100.0
        else:
            efficiency = (unique_entries / total_attempts) * 100
        
        return jsonify({
            'total_attempts': total_attempts,
            'unique_entries': unique_entries,
            'efficiency': f"{efficiency:.1f}%",
            'duplicates_prevented': total_attempts - unique_entries
        })
    except Exception as e:
        print(f"❌ Error loading stats: {e}")
        return jsonify({
            'total_attempts': 0,
            'unique_entries': 0,
            'efficiency': '100%',
            'duplicates_prevented': 0,
            'error': str(e)
        })

@app.route('/api/clear', methods=['POST'])
def clear_data():
    """Clear all data (testing only)"""
    try:
        if not client:
            return jsonify({
                'success': False,
                'error': 'Database not connected'
            })
            
        users_result = users_collection.delete_many({})
        attempts_result = attempts_collection.delete_many({})
        print(f"🗑️ Database cleared: {users_result.deleted_count} users, {attempts_result.deleted_count} attempts")
        return jsonify({
            'success': True,
            'message': f'Database cleared. {users_result.deleted_count} users and {attempts_result.deleted_count} attempts removed.'
        })
    except Exception as e:
        print(f"❌ Error clearing database: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        if client:
            client.admin.command('ping')
            return jsonify({
                'status': 'healthy',
                'database': 'connected',
                'message': 'System operational'
            })
        else:
            return jsonify({
                'status': 'unhealthy',
                'database': 'disconnected',
                'message': 'MongoDB connection failed'
            }), 503
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'database': 'error',
            'message': str(e)
        }), 503

if __name__ == '__main__':
    app.run(debug=True)
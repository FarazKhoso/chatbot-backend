from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from flask_jwt_extended import JWTManager, jwt_required, create_access_token, get_jwt_identity
import google.generativeai as genai
import os
import json
from dotenv import load_dotenv
from datetime import datetime, timedelta
import bcrypt
import re
import uuid

load_dotenv()

app = Flask(__name__)
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'your-default-secret-key-change-this')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

CORS(app)  # Enable CORS for all routes
jwt = JWTManager(app)

# In-memory storage for users and conversations (for testing)
users_db = {}
conversations_db = {}

# Generate a unique ID function
def generate_id():
    return str(uuid.uuid4())

# Configure the API key
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY environment variable is not set")

genai.configure(api_key=api_key)

# Get the model
model = genai.GenerativeModel('gemini-2.0-flash')

@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        email = data.get('email', '').lower().strip()
        password = data.get('password', '')

        # Validate input
        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400

        # Basic email validation
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return jsonify({'error': 'Invalid email format'}), 400

        # Check if user already exists
        for user in users_db.values():
            if user['email'] == email:
                return jsonify({'error': 'User with this email already exists'}), 409

        # Hash the password
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

        # Create new user
        user_id = generate_id()
        user_data = {
            'id': user_id,
            'email': email,
            'password': hashed_password.decode('utf-8'),
            'created_at': datetime.utcnow().isoformat()
        }
        users_db[user_id] = user_data

        return jsonify({'message': 'User registered successfully'}), 201
    except Exception as e:
        print(f"Error registering user: {str(e)}")
        return jsonify({'error': 'Failed to register user'}), 500

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        email = data.get('email', '').lower().strip()
        password = data.get('password', '')

        # Validate input
        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400

        # Find user in database
        user = None
        for u in users_db.values():
            if u['email'] == email:
                user = u
                break

        if not user:
            return jsonify({'error': 'Invalid credentials'}), 401

        # Check password
        if not bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
            return jsonify({'error': 'Invalid credentials'}), 401

        # Generate JWT token
        access_token = create_access_token(identity=user['id'])
        return jsonify({
            'access_token': access_token,
            'user': {
                'email': user['email'],
                'id': user['id']
            }
        }), 200
    except Exception as e:
        print(f"Error logging in user: {str(e)}")
        return jsonify({'error': 'Failed to login user'}), 500

@app.route('/api/chat', methods=['POST'])
@jwt_required()
def chat():
    try:
        current_user_id = get_jwt_identity()
        data = request.json
        user_message = data.get('message', '')
        conversation_id = data.get('conversation_id')  # Optional - if part of existing conversation

        # Generate response using the model
        response = model.generate_content(user_message)

        # Extract the text from the response
        response_text = response.text if response.text else "I couldn't generate a response."

        # Create or update conversation
        message_entry = {
            'role': 'user',
            'content': user_message,
            'timestamp': datetime.utcnow().isoformat()
        }
        assistant_entry = {
            'role': 'assistant',
            'content': response_text,
            'timestamp': datetime.utcnow().isoformat()
        }

        if conversation_id:
            # Check if conversation exists and belongs to user
            if conversation_id not in conversations_db or conversations_db[conversation_id]['user_id'] != current_user_id:
                return jsonify({'error': 'Conversation not found or access denied'}), 404

            # Add to existing conversation
            conversations_db[conversation_id]['messages'].extend([message_entry, assistant_entry])
            conversations_db[conversation_id]['updated_at'] = datetime.utcnow().isoformat()
        else:
            # Create new conversation
            conversation_id = generate_id()
            title = user_message[:50] + "..." if len(user_message) > 50 else user_message
            conversation_data = {
                'id': conversation_id,
                'user_id': current_user_id,
                'title': title,
                'messages': [message_entry, assistant_entry],
                'created_at': datetime.utcnow().isoformat(),
                'updated_at': datetime.utcnow().isoformat()
            }
            conversations_db[conversation_id] = conversation_data

        return jsonify({
            'response': response_text,
            'conversation_id': conversation_id
        })

    except Exception as e:
        print(f"Error processing chat request: {str(e)}")
        return jsonify({'error': f'Failed to process the request: {str(e)}'}), 500

@app.route('/api/chat-stream', methods=['POST'])
@jwt_required()
def chat_stream():
    current_user_id = get_jwt_identity()
    data = request.get_json()
    user_message = data.get('message', '') if data else ''
    conversation_id = data.get('conversation_id')  # Optional - if part of existing conversation

    def generate():
        try:
            # Start a chat session for streaming
            chat = model.start_chat()

            # Generate response using the chat with streaming
            response = chat.send_message(user_message, stream=True)

            accumulated_text = ""
            for chunk in response:
                if chunk.text:  # Only send non-empty chunks
                    accumulated_text += chunk.text
                    yield f"data: {json.dumps({'text': chunk.text})}\n\n"

            # Create or update conversation in memory after streaming is complete
            message_entry = {
                'role': 'user',
                'content': user_message,
                'timestamp': datetime.utcnow().isoformat()
            }
            assistant_entry = {
                'role': 'assistant',
                'content': accumulated_text,
                'timestamp': datetime.utcnow().isoformat()
            }

            if conversation_id:
                # Check if conversation exists and belongs to user
                if conversation_id not in conversations_db or conversations_db[conversation_id]['user_id'] != current_user_id:
                    # If conversation doesn't exist, send error via SSE
                    error_response = '{"error": "Conversation not found or access denied"}'
                    yield f"data: {error_response}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                # Add to existing conversation
                conversations_db[conversation_id]['messages'].extend([message_entry, assistant_entry])
                conversations_db[conversation_id]['updated_at'] = datetime.utcnow().isoformat()
            else:
                # Create new conversation
                new_conversation_id = generate_id()
                title = user_message[:50] + "..." if len(user_message) > 50 else user_message
                conversation_data = {
                    'id': new_conversation_id,
                    'user_id': current_user_id,
                    'title': title,
                    'messages': [message_entry, assistant_entry],
                    'created_at': datetime.utcnow().isoformat(),
                    'updated_at': datetime.utcnow().isoformat()
                }
                conversations_db[new_conversation_id] = conversation_data
                # Send the new conversation ID back to the client
                yield f"data: {json.dumps({'conversation_id': new_conversation_id})}\n\n"

            # Send end indicator
            yield "data: [DONE]\n\n"
        except Exception as e:
            print(f"Error processing streaming chat request: {str(e)}")
            # Avoid context issues by directly creating JSON string
            error_response = '{"error": "Failed to process the request: ' + str(e).replace('"', "'") + '"}'
            yield f"data: {error_response}\n\n"
            yield "data: [DONE]\n\n"

    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/conversations', methods=['GET'])
@jwt_required()
def get_conversations():
    try:
        current_user_id = get_jwt_identity()

        # Get all conversations for the user, sorted by updated date (most recent first)
        user_conversations = []
        for conv in conversations_db.values():
            if conv['user_id'] == current_user_id:
                user_conversations.append({
                    'id': conv['id'],
                    'title': conv.get('title', 'New Conversation'),
                    'created_at': conv.get('created_at'),
                    'updated_at': conv.get('updated_at'),
                    'message_count': len(conv.get('messages', []))
                })

        # Sort by updated date (most recent first)
        user_conversations.sort(key=lambda x: x['updated_at'], reverse=True)

        return jsonify({'conversations': user_conversations}), 200
    except Exception as e:
        print(f"Error fetching conversations: {str(e)}")
        return jsonify({'error': f'Failed to fetch conversations: {str(e)}'}), 500

@app.route('/api/conversation/<conversation_id>', methods=['GET'])
@jwt_required()
def get_conversation(conversation_id):
    try:
        current_user_id = get_jwt_identity()

        # Get specific conversation for the user
        conversation = conversations_db.get(conversation_id)

        if not conversation or conversation['user_id'] != current_user_id:
            return jsonify({'error': 'Conversation not found'}), 404

        # Format the conversation
        formatted_conversation = {
            'id': conversation['id'],
            'title': conversation.get('title', 'New Conversation'),
            'created_at': conversation.get('created_at'),
            'updated_at': conversation.get('updated_at'),
            'messages': conversation.get('messages', []),
            'message_count': len(conversation.get('messages', []))
        }

        return jsonify({'conversation': formatted_conversation}), 200
    except Exception as e:
        print(f"Error fetching conversation: {str(e)}")
        return jsonify({'error': f'Failed to fetch conversation: {str(e)}'}), 500

@app.route('/api/conversation/<conversation_id>', methods=['DELETE'])
@jwt_required()
def delete_conversation(conversation_id):
    try:
        current_user_id = get_jwt_identity()

        # Delete specific conversation for the user
        conversation = conversations_db.get(conversation_id)

        if not conversation or conversation['user_id'] != current_user_id:
            return jsonify({'error': 'Conversation not found'}), 404

        del conversations_db[conversation_id]

        return jsonify({'message': 'Conversation deleted successfully'}), 200
    except Exception as e:
        print(f"Error deleting conversation: {str(e)}")
        return jsonify({'error': f'Failed to delete conversation: {str(e)}'}), 500

@app.route('/api/user/profile', methods=['GET'])
@jwt_required()
def get_user_profile():
    try:
        current_user_id = get_jwt_identity()

        # Get user info from memory
        user = users_db.get(current_user_id)

        if not user:
            return jsonify({'error': 'User not found'}), 404

        return jsonify({
            'user': {
                'id': user['id'],
                'email': user['email'],
                'created_at': user.get('created_at')
            }
        }), 200
    except Exception as e:
        print(f"Error fetching user profile: {str(e)}")
        return jsonify({'error': f'Failed to fetch user profile: {str(e)}'}), 500

@app.route('/test')
def test():
    return "this is test page"


if __name__ == '__main__':
    app.run(debug=True, port=5001)
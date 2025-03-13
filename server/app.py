import socketio
import eventlet
import socket
import logging
import time
import os
from flask import Flask, render_template, request, jsonify
import json
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize Flask app and Socket.IO
app = Flask(__name__)
sio = socketio.Server(cors_allowed_origins='*')
app.wsgi_app = socketio.WSGIApp(sio, app.wsgi_app)

# Global variables
clients = {}
chat_history = []
MAX_HISTORY = 100  # Maximum number of messages to keep in history
MAX_HISTORY_TO_SEND = 20  # Maximum number of messages to send to new clients

# Store server start time (moved to global scope)
server_start_time = time.time()

def get_ip_address():
    """Get the primary IP address of the machine"""
    try:
        # When deployed on Render, use environment variable
        if 'RENDER' in os.environ:
            return os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'render-host')
        
        # For local development
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

@sio.event
def connect(sid, environ):
    """Handle client connection"""
    client_ip = environ.get('REMOTE_ADDR', 'Unknown')
    logger.info(f"Client connected: {sid} from {client_ip}")
    clients[sid] = {
        'username': f"Guest_{sid[:4]}",
        'connected_at': time.time(),
        'ip': client_ip
    }
    
    # Send welcome message and notify others
    welcome_msg = {
        'type': 'system',
        'text': f"Welcome to the chat, {clients[sid]['username']}! Type /clear to clear your chat history.",
        'timestamp': datetime.now().strftime("%H:%M:%S")
    }
    sio.emit('message', welcome_msg, room=sid)
    
    # Send limited history to new client (only recent messages)
    recent_history = chat_history[-MAX_HISTORY_TO_SEND:] if chat_history else []
    if recent_history:
        history_notice = {
            'type': 'system',
            'text': f"Showing last {len(recent_history)} messages",
            'timestamp': datetime.now().strftime("%H:%M:%S")
        }
        sio.emit('message', history_notice, room=sid)
        
        for msg in recent_history:
            sio.emit('message', msg, room=sid)
    
    # Notify all users about new connection
    join_msg = {
        'type': 'system',
        'text': f"{clients[sid]['username']} has joined the chat",
        'timestamp': datetime.now().strftime("%H:%M:%S")
    }
    sio.emit('message', join_msg, skip_sid=sid)
    
    # Send updated user list to all clients
    emit_user_list()

@sio.event
def disconnect(sid):
    """Handle client disconnection"""
    if sid in clients:
        username = clients[sid]['username']
        logger.info(f"Client disconnected: {username} ({sid})")
        
        # Notify remaining users
        leave_msg = {
            'type': 'system',
            'text': f"{username} has left the chat",
            'timestamp': datetime.now().strftime("%H:%M:%S")
        }
        sio.emit('message', leave_msg)
        
        # Remove from clients list
        del clients[sid]
        
        # Send updated user list
        emit_user_list()

@sio.event
def chat_message(sid, data):
    """Handle incoming chat messages"""
    if sid not in clients:
        return
    
    username = clients[sid]['username']
    text = data.get('text', '').strip()
    
    if not text:
        return
    
    # Check for clear history command
    if text.lower() == "/clear":
        # Clear only for this user
        clear_msg = {
            'type': 'system',
            'text': "Chat history cleared for you",
            'timestamp': datetime.now().strftime("%H:%M:%S"),
            'clear': True  # Special flag for client to clear history
        }
        sio.emit('message', clear_msg, room=sid)
        return
    
    # Create message object
    msg = {
        'type': 'chat',
        'username': username,
        'text': text,
        'timestamp': datetime.now().strftime("%H:%M:%S")
    }
    
    # Add to history and limit size
    chat_history.append(msg)
    if len(chat_history) > MAX_HISTORY:
        chat_history.pop(0)
    
    # Broadcast to all clients
    logger.info(f"Message from {username}: {text}")
    sio.emit('message', msg)

@sio.event
def set_username(sid, data):
    """Handle username change request"""
    if sid not in clients:
        return
    
    old_username = clients[sid]['username']
    new_username = data.get('username', '').strip()
    
    # Validate new username
    if not new_username or len(new_username) > 20 or new_username in [client['username'] for _, client in clients.items() if _ != sid]:
        # Send error if username is invalid or already taken
        sio.emit('username_error', {'error': 'Invalid username or already taken'}, room=sid)
        return
    
    # Update username
    clients[sid]['username'] = new_username
    
    # Notify all users about the change
    change_msg = {
        'type': 'system',
        'text': f"{old_username} changed their name to {new_username}",
        'timestamp': datetime.now().strftime("%H:%M:%S")
    }
    sio.emit('message', change_msg)
    
    # Send success response to the client
    sio.emit('username_changed', {'username': new_username}, room=sid)
    
    # Send updated user list
    emit_user_list()

def emit_user_list():
    """Send updated user list to all clients"""
    users = [{'id': sid, 'username': data['username']} for sid, data in clients.items()]
    sio.emit('user_list', {'users': users})

@app.route('/')
def index():
    """Serve a simple status page"""
    server_url = request.url_root.rstrip('/')
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>IP Chat Server</title>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 20px; }}
            h1 {{ color: #4a6fa5; }}
            .card {{ background: #f5f5f5; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
            pre {{ background: #e0e0e0; padding: 10px; border-radius: 3px; overflow-x: auto; }}
            .success {{ color: #28a745; }}
        </style>
    </head>
    <body>
        <h1>IP Chat Server</h1>
        
        <div class="card">
            <h2>Server Status: <span class="success">Running</span></h2>
            <p>Server URL: <code>{server_url}</code></p>
            <p>Connected users: <strong>{len(clients)}</strong></p>
            <p>Messages in history: <strong>{len(chat_history)}</strong></p>
            <p>Server uptime: <strong>{int((time.time() - server_start_time) / 60)} minutes</strong></p>
        </div>
        
        <div class="card">
            <h2>How to Connect</h2>
            <p>To use this chat server:</p>
            <ol>
                <li>Open the client URL: <a href="{server_url}/client" target="_blank">{server_url}/client</a></li>
                <li>Enter this server URL: <code>{server_url}</code></li>
                <li>Click Connect</li>
            </ol>
            <p>You can share this server URL with anyone to let them connect to your chat!</p>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/client')
def client():
    """Serve the client page"""
    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'client', 'index.html'), 'r') as f:
        content = f.read()
    return content

@app.route('/stats')
def stats():
    """Return server statistics"""
    return jsonify({
        'active_users': len(clients),
        'message_count': len(chat_history),
        'uptime': time.time() - server_start_time
    })

# Get the port from the environment variable (for Render)
port = int(os.environ.get('PORT', 5000))

if __name__ == '__main__':
    logger.info("=" * 50)
    logger.info("IP Chat Server")
    logger.info("=" * 50)
    logger.info(f"Running on port: {port}")
    if 'RENDER' in os.environ:
        logger.info(f"Detected Render.com environment")
        host_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}"
        logger.info(f"Public URL: {host_url}")
    else:
        logger.info(f"Local URL: http://localhost:{port}")
    logger.info("=" * 50)
    
    # Start the server
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app) 

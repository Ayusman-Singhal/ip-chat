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

# Get the production flag from environment (Render is production)
is_production = 'RENDER' in os.environ

# Initialize Flask app and Socket.IO
app = Flask(__name__)
# Configure Socket.IO with more permissive CORS
socketio_kwargs = {
    'cors_allowed_origins': '*',
    'async_mode': 'eventlet',
    'logger': True,
    'engineio_logger': True  # Log engine.io messages too
}
sio = socketio.Server(**socketio_kwargs)
app.wsgi_app = socketio.WSGIApp(sio, app.wsgi_app)

# Add CORS headers to all responses
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

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
    logger.info(f"Connection environ: {environ.get('HTTP_ORIGIN', 'No origin')} via {environ.get('HTTP_USER_AGENT', 'Unknown UA')}")
    
    clients[sid] = {
        'username': f"Guest_{sid[:4]}",
        'connected_at': time.time(),
        'ip': client_ip
    }
    
    # Calculate current timestamp
    now = datetime.now()
    timestamp = now.strftime("%H:%M:%S")
    time_ms = int(time.time() * 1000)
    
    # Send welcome message and notify others
    welcome_msg = {
        'type': 'system',
        'text': f"Welcome to the chat, {clients[sid]['username']}! Type /clear to clear your chat history.",
        'timestamp': timestamp,
        'id': f"welcome_{sid}_{time_ms}"
    }
    sio.emit('message', welcome_msg, room=sid)
    
    # Send limited history to new client (only recent messages)
    recent_history = chat_history[-MAX_HISTORY_TO_SEND:] if chat_history else []
    if recent_history:
        history_notice = {
            'type': 'system',
            'text': f"Showing last {len(recent_history)} messages",
            'timestamp': timestamp,
            'id': f"history_notice_{sid}_{time_ms}"
        }
        sio.emit('message', history_notice, room=sid)
        
        for msg in recent_history:
            sio.emit('message', msg, room=sid)
    
    # Notify all users about new connection
    join_msg = {
        'type': 'system',
        'text': f"{clients[sid]['username']} has joined the chat",
        'timestamp': timestamp,
        'id': f"join_{sid}_{time_ms}"
    }
    sio.emit('message', join_msg, skip_sid=sid)
    
    # Send updated user list to all clients
    emit_user_list()

@sio.event
def connect_error(data):
    """Log connection errors"""
    logger.error(f"Connection error: {data}")

@sio.event
def disconnect(sid):
    """Handle client disconnection"""
    if sid in clients:
        username = clients[sid]['username']
        logger.info(f"Client disconnected: {username} ({sid})")
        
        # Get current timestamp
        timestamp = datetime.now().strftime("%H:%M:%S")
        time_ms = int(time.time() * 1000)
        
        # Notify remaining users
        leave_msg = {
            'type': 'system',
            'text': f"{username} has left the chat",
            'timestamp': timestamp,
            'id': f"leave_{sid}_{time_ms}"
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
            'clear': True,  # Special flag for client to clear history
            'id': f"clear_{sid}_{int(time.time()*1000)}"  # Add unique ID
        }
        sio.emit('message', clear_msg, room=sid)
        return
    
    # Generate a timestamp for the message
    timestamp = datetime.now().strftime("%H:%M:%S")
    message_time = int(time.time() * 1000)  # Milliseconds since epoch
    
    # Create message object
    msg = {
        'type': 'chat',
        'username': username,
        'text': text,
        'timestamp': timestamp,
        'id': f"msg_{message_time}_{sid}"  # Add unique ID
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
    
    # Get current timestamp
    timestamp = datetime.now().strftime("%H:%M:%S")
    time_ms = int(time.time() * 1000)
    
    # Notify all users about the change
    change_msg = {
        'type': 'system',
        'text': f"{old_username} changed their name to {new_username}",
        'timestamp': timestamp,
        'id': f"rename_{sid}_{time_ms}"
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
    ssl_enabled = request.is_secure or server_url.startswith('https://')
    
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
            .warning {{ color: #ffc107; }}
            .code {{ font-family: monospace; background: #e0e0e0; padding: 2px 4px; }}
        </style>
    </head>
    <body>
        <h1>IP Chat Server</h1>
        
        <div class="card">
            <h2>Server Status: <span class="success">Running</span></h2>
            <p>Server URL: <code>{server_url}</code></p>
            <p>SSL/HTTPS: <span class="{'success' if ssl_enabled else 'warning'}">{ssl_enabled}</span></p>
            <p>Connected users: <strong>{len(clients)}</strong></p>
            <p>Messages in history: <strong>{len(chat_history)}</strong></p>
            <p>Server uptime: <strong>{int((time.time() - server_start_time) / 60)} minutes</strong></p>
        </div>
        
        <div class="card">
            <h2>How to Connect</h2>
            <p>To use this chat server:</p>
            <ol>
                <li>Open the client URL: <a href="{server_url}/client" target="_blank">{server_url}/client</a></li>
                <li>The server URL should be auto-filled: <code>{server_url}</code></li>
                <li>Click Connect</li>
                <li>If you have trouble connecting, make sure you're using the same protocol (HTTP or HTTPS)</li>
            </ol>
            <p>You can share this server URL with anyone to let them connect to your chat!</p>
        </div>
        
        <div class="card">
            <h2>Troubleshooting</h2>
            <p>If you have trouble connecting:</p>
            <ul>
                <li>Open your browser's console (F12) to check for connection errors</li>
                <li>Make sure the client and server both use the same protocol (HTTP or HTTPS)</li>
                <li>If using HTTPS, ensure the Socket.IO connection also uses secure WebSockets (wss://)</li>
                <li>Try opening the client in a private/incognito window to avoid cached resources</li>
            </ul>
            <p>Server-side logs are available in your Render dashboard.</p>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/client')
def client():
    """Serve the client page"""
    try:
        # Log the current path to help debug
        client_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'client', 'index.html')
        logger.info(f"Attempting to read client from: {client_path}")
        
        # Check if the file exists
        if not os.path.exists(client_path):
            logger.error(f"Client file not found at: {client_path}")
            
            # Try an alternative path directly in the app directory
            alt_path = os.path.join(os.path.dirname(__file__), 'client.html')
            if os.path.exists(alt_path):
                logger.info(f"Found client at alternative path: {alt_path}")
                with open(alt_path, 'r') as f:
                    content = f.read()
                return content
            
            # If still not found, embed a basic client directly
            logger.info("Serving embedded client HTML")
            return """
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>IP Chat</title>
                <style>
                    :root {
                        --primary-color: #4a6fa5;
                        --secondary-color: #6c8ebd;
                        --background-color: #f5f5f5;
                        --chat-bg: #ffffff;
                        --text-color: #333333;
                        --system-msg-color: #6c757d;
                        --my-msg-bg: #e3f2fd;
                        --other-msg-bg: #f8f9fa;
                        --border-color: #dee2e6;
                    }
                    * { box-sizing: border-box; margin: 0; padding: 0; }
                    body {
                        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                        background-color: var(--background-color);
                        color: var(--text-color);
                        line-height: 1.6;
                        height: 100vh;
                        display: flex;
                        flex-direction: column;
                    }
                    header {
                        background-color: var(--primary-color);
                        color: white;
                        padding: 1rem;
                        text-align: center;
                        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                    }
                    .main-container {
                        display: flex;
                        flex: 1;
                        overflow: hidden;
                    }
                    .sidebar {
                        width: 250px;
                        background-color: white;
                        border-right: 1px solid var(--border-color);
                        display: flex;
                        flex-direction: column;
                    }
                    .chat-container {
                        flex: 1;
                        display: flex;
                        flex-direction: column;
                        overflow: hidden;
                    }
                    .connection-panel, .username-panel {
                        padding: 1rem;
                        background-color: white;
                        border-bottom: 1px solid var(--border-color);
                    }
                    .form-group {
                        margin-bottom: 1rem;
                    }
                    label {
                        display: block;
                        margin-bottom: 0.5rem;
                        font-weight: 500;
                    }
                    input, button {
                        width: 100%;
                        padding: 0.75rem;
                        border: 1px solid var(--border-color);
                        border-radius: 4px;
                        font-size: 1rem;
                    }
                    button {
                        background-color: var(--primary-color);
                        color: white;
                        border: none;
                        cursor: pointer;
                    }
                    .chat-messages {
                        flex: 1;
                        padding: 1rem;
                        overflow-y: auto;
                        background-color: var(--chat-bg);
                    }
                    .chat-input {
                        display: flex;
                        padding: 1rem;
                        background-color: white;
                        border-top: 1px solid var(--border-color);
                    }
                    .chat-input input {
                        flex: 1;
                        margin-right: 0.5rem;
                    }
                    .chat-input button {
                        width: auto;
                    }
                    .message {
                        margin-bottom: 1rem;
                        padding: 0.75rem;
                        border-radius: 4px;
                    }
                    .message-system {
                        background-color: #f8f9fa;
                        color: var(--system-msg-color);
                        text-align: center;
                        font-style: italic;
                    }
                    .message-mine {
                        background-color: var(--my-msg-bg);
                        margin-left: 2rem;
                    }
                    .message-other {
                        background-color: var(--other-msg-bg);
                        margin-right: 2rem;
                    }
                    .message-header {
                        display: flex;
                        justify-content: space-between;
                        margin-bottom: 0.5rem;
                        font-size: 0.875rem;
                    }
                    .message-username {
                        font-weight: bold;
                    }
                    .message-timestamp {
                        color: var(--system-msg-color);
                    }
                    .users {
                        list-style: none;
                    }
                    .users li {
                        padding: 0.5rem 1rem;
                        border-bottom: 1px solid var(--border-color);
                    }
                    @media (max-width: 768px) {
                        .main-container {
                            flex-direction: column;
                        }
                        .sidebar {
                            width: 100%;
                            max-height: 50%;
                        }
                    }
                </style>
            </head>
            <body>
                <header>
                    <h1>IP Chat</h1>
                </header>
                <div class="main-container">
                    <div class="sidebar" id="sidebar">
                        <div class="connection-panel">
                            <div class="form-group">
                                <label for="server-address">Server Address:</label>
                                <input type="text" id="server-address" placeholder="Enter IP address or hostname:port">
                            </div>
                            <div class="form-group">
                                <button id="connect-btn">Connect</button>
                                <button id="disconnect-btn" style="display: none;">Disconnect</button>
                            </div>
                            <div class="form-group">
                                <label for="username">Username:</label>
                                <input type="text" id="username" placeholder="Enter username" disabled>
                                <button id="change-username-btn" disabled>Change</button>
                            </div>
                        </div>
                        <div class="status-bar">
                            <div id="status-indicator"></div>
                            <span id="status-text">Disconnected</span>
                        </div>
                        <div class="user-list">
                            <h3>Online Users (0)</h3>
                            <ul class="users" id="users-list"></ul>
                        </div>
                    </div>
                    <div class="chat-container">
                        <div class="chat-messages" id="chat-messages">
                            <div class="message message-system">
                                Welcome to IP Chat! Connect to a server to start chatting.
                            </div>
                        </div>
                        <div class="chat-input">
                            <input type="text" id="message-input" placeholder="Type a message..." disabled>
                            <button id="send-btn" disabled>Send</button>
                        </div>
                    </div>
                </div>
                <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
                <script>
                    // DOM Elements
                    const serverAddressInput = document.getElementById('server-address');
                    const connectBtn = document.getElementById('connect-btn');
                    const disconnectBtn = document.getElementById('disconnect-btn');
                    const usernameInput = document.getElementById('username');
                    const changeUsernameBtn = document.getElementById('change-username-btn');
                    const statusIndicator = document.getElementById('status-indicator');
                    const statusText = document.getElementById('status-text');
                    const usersList = document.getElementById('users-list');
                    const chatMessages = document.getElementById('chat-messages');
                    const messageInput = document.getElementById('message-input');
                    const sendBtn = document.getElementById('send-btn');

                    // Variables
                    let socket;
                    let connected = false;
                    let currentUsername = '';
                    let processedMessageIds = new Set(); // Track message IDs to prevent duplicates

                    serverAddressInput.value = `https://ip-chat.onrender.com`;

                    // Event Listeners
                    connectBtn.addEventListener('click', connectToServer);
                    disconnectBtn.addEventListener('click', handleDisconnect);
                    changeUsernameBtn.addEventListener('click', changeUsername);
                    sendBtn.addEventListener('click', sendMessage);
                    messageInput.addEventListener('keypress', function(e) {
                        if (e.key === 'Enter') sendMessage();
                    });

                    // Function to connect to the server
                    function connectToServer() {
                        const serverAddress = serverAddressInput.value.trim();
                        if (!serverAddress) {
                            alert('Please enter a server address');
                            return;
                        }

                        connectBtn.disabled = true;
                        statusText.textContent = 'Connecting...';

                        try {
                            console.log('Connecting to:', serverAddress);
                            // Create Socket.IO connection with explicit transports
                            socket = io(serverAddress, {
                                transports: ['websocket', 'polling'],
                                reconnectionAttempts: 3,
                                timeout: 10000
                            });

                            // Set up connection timeout
                            const connectionTimeout = setTimeout(() => {
                                if (!connected) {
                                    console.error('Connection timed out');
                                    if (socket) {
                                        socket.close();
                                    }
                                    handleDisconnect();
                                    alert('Connection timed out. Please check the server address and try again.');
                                }
                            }, 10000);

                            socket.on('connect', function() {
                                clearTimeout(connectionTimeout);
                                console.log('Connected successfully to:', serverAddress);
                                connected = true;
                                connectBtn.style.display = 'none';
                                disconnectBtn.style.display = 'block';
                                usernameInput.disabled = false;
                                changeUsernameBtn.disabled = false;
                                messageInput.disabled = false;
                                sendBtn.disabled = false;

                                statusIndicator.className = 'status-indicator status-connected';
                                statusText.textContent = 'Connected';

                                // Add initial system message
                                addSystemMessage('Connected to server', 'connect_' + Date.now());
                            });

                            socket.on('disconnect', function() {
                                handleDisconnect();
                                addSystemMessage('Disconnected from server');
                            });

                            // Chat events
                            socket.on('message', function(message) {
                                if (message.type === 'system') {
                                    if (message.clear) {
                                        clearChatHistory();
                                        addSystemMessage(message.text);
                                    } else {
                                        addSystemMessage(message.text);
                                    }
                                } else if (message.type === 'chat') {
                                    addChatMessage(message);
                                }
                            });

                            socket.on('user_list', function(data) {
                                updateUserList(data.users);
                            });

                            socket.on('username_changed', function(data) {
                                currentUsername = data.username;
                                usernameInput.value = currentUsername;
                            });

                            socket.on('username_error', function(data) {
                                alert(data.error);
                            });

                        } catch (error) {
                            console.error('Error connecting to server:', error);
                            handleDisconnect();
                            alert('Failed to connect to server. Please check the address and try again.');
                        }
                    }

                    function handleDisconnect() {
                        connected = false;
                        connectBtn.style.display = 'block';
                        disconnectBtn.style.display = 'none';
                        connectBtn.disabled = false;
                        usernameInput.disabled = true;
                        changeUsernameBtn.disabled = true;
                        messageInput.disabled = true;
                        sendBtn.disabled = true;

                        statusIndicator.className = 'status-indicator status-disconnected';
                        statusText.textContent = 'Disconnected';

                        currentUsername = '';
                        usernameInput.value = '';
                        
                        // Clear user list
                        usersList.innerHTML = '';
                        
                        if (socket) {
                            socket.disconnect();
                            socket = null;
                        }
                    }

                    function sendMessage() {
                        if (!connected) return;

                        const text = messageInput.value.trim();
                        if (!text) return;

                        // Send the message to the server
                        socket.emit('chat_message', { text });

                        // Clear input field
                        messageInput.value = '';
                    }

                    function changeUsername() {
                        if (!connected) return;

                        const newUsername = usernameInput.value.trim();
                        if (!newUsername) {
                            alert('Username cannot be empty');
                            return;
                        }

                        socket.emit('set_username', { username: newUsername });
                    }

                    function addSystemMessage(text, messageId) {
                        // Create unique ID if not provided
                        const id = messageId || 'sys_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
                        
                        // Check if we've already processed this message
                        if (processedMessageIds.has(id)) {
                            console.log('Skipping duplicate system message:', id);
                            return;
                        }
                        
                        // Mark as processed
                        processedMessageIds.add(id);
                        
                        const messageElem = document.createElement('div');
                        messageElem.className = 'message message-system';
                        messageElem.dataset.messageId = id;
                        messageElem.textContent = text;
                        chatMessages.appendChild(messageElem);
                        scrollToBottom();
                    }

                    function addChatMessage(message) {
                        // Generate or use message ID
                        const id = message.id || `msg_${message.timestamp}_${message.username}_${message.text.substr(0, 10)}`;
                        
                        // Check if we've already processed this message
                        if (processedMessageIds.has(id)) {
                            console.log('Skipping duplicate chat message:', id);
                            return;
                        }
                        
                        // Mark as processed
                        processedMessageIds.add(id);
                        
                        const isMine = message.username === currentUsername;
                        
                        const messageElem = document.createElement('div');
                        messageElem.className = isMine ? 'message message-mine' : 'message message-other';
                        messageElem.dataset.messageId = id;
                        
                        const headerElem = document.createElement('div');
                        headerElem.className = 'message-header';
                        
                        const usernameElem = document.createElement('span');
                        usernameElem.className = 'message-username';
                        usernameElem.textContent = message.username;
                        
                        const timestampElem = document.createElement('span');
                        timestampElem.className = 'message-timestamp';
                        timestampElem.textContent = message.timestamp;
                        
                        headerElem.appendChild(usernameElem);
                        headerElem.appendChild(timestampElem);
                        
                        const textElem = document.createElement('div');
                        textElem.className = 'message-text';
                        textElem.textContent = message.text;
                        
                        messageElem.appendChild(headerElem);
                        messageElem.appendChild(textElem);
                        
                        chatMessages.appendChild(messageElem);
                        scrollToBottom();
                    }

                    function updateUserList(users) {
                        usersList.innerHTML = '';
                        
                        const usersHeading = document.querySelector('.user-list h3');
                        usersHeading.textContent = `Online Users (${users.length})`;
                        
                        users.forEach(user => {
                            const li = document.createElement('li');
                            li.textContent = user.username;
                            if (user.username === currentUsername) {
                                li.style.fontWeight = 'bold';
                            }
                            usersList.appendChild(li);
                        });
                    }

                    function scrollToBottom() {
                        chatMessages.scrollTop = chatMessages.scrollHeight;
                    }

                    function clearChatHistory() {
                        // Don't clear processedMessageIds - that's our duplicate prevention mechanism
                        
                        // Keep only the welcome message
                        const welcomeMessage = chatMessages.querySelector('.message-system');
                        chatMessages.innerHTML = '';
                        if (welcomeMessage) {
                            chatMessages.appendChild(welcomeMessage);
                        }
                    }

                    // Add function to handle server disconnect and reconnect
                    function handleServerReconnect() {
                        // Don't clear message IDs so we can prevent duplicates on reconnect
                        // But we should clear the visible messages to avoid confusion
                        clearChatHistory();
                        addSystemMessage('Reconnected to server. History will be restored.');
                    }
                </script>
            </body>
            </html>
            """
        
        # Normal path handling if file exists
        with open(client_path, 'r') as f:
            content = f.read()
        return content
    except Exception as e:
        logger.error(f"Error serving client: {e}")
        # Return an error message instead of failing
        return f"""
        <html>
        <head><title>Client Error</title></head>
        <body>
            <h1>Error loading chat client</h1>
            <p>There was an error loading the chat client: {str(e)}</p>
            <p>Please contact the administrator.</p>
        </body>
        </html>
        """

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

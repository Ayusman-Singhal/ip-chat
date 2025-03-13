import os
import sys
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    """Start the IP Chat server"""
    logger.info("Starting IP Chat Server for Render...")
    
    # Add the current directory to sys.path so we can import the server module
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    
    # Import and run the server
    try:
        from server.app import app, sio, server_start_time, port, eventlet
        
        logger.info(f"Server starting on port {port}")
        eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
    except Exception as e:
        logger.error(f"Error starting server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 
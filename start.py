import os
import sys
import logging
import time

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
        logger.info("Importing server modules...")
        import eventlet
        from server.app import app, port
        
        # Log environment information
        logger.info(f"Python version: {sys.version}")
        logger.info(f"Current directory: {os.getcwd()}")
        logger.info(f"Available files: {os.listdir('.')}")
        logger.info(f"Server port: {port}")
        
        if 'RENDER' in os.environ:
            logger.info(f"Running on Render.com")
            logger.info(f"RENDER_EXTERNAL_HOSTNAME: {os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'not set')}")
        
        logger.info(f"Server starting on port {port}")
        eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)
    except ImportError as e:
        logger.error(f"Import error: {e}")
        logger.error(f"This usually means a required module is missing or the path structure is incorrect.")
        
        # Log more details to help debug
        logger.info(f"sys.path: {sys.path}")
        if os.path.exists('server'):
            logger.info(f"Contents of server directory: {os.listdir('server')}")
        
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error starting server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 

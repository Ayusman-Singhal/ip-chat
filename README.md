# IP Chat - Render Deployment

This folder contains a simplified version of IP Chat optimized for deployment on Render.com.

## Features

- No dependencies on UPnP or ngrok (not needed on cloud hosting)
- Automatic environment detection for Render
- Integrated client and server (client is served directly by the server)
- Simple deployment process

## Deploying to Render

1. Create a new Web Service on Render
2. Connect to your GitHub repository
3. Configure as follows:
   - **Name**: Choose a name (e.g., "ip-chat")
   - **Root Directory**: `render` (this directory)
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python start.py`
   - **Instance Type**: Free (or paid if you need better performance)

That's it! Render will automatically deploy your application and provide a public URL.

## Using the Deployed Chat

Once deployed:

1. Visit your Render URL (e.g., `https://ip-chat.onrender.com`)
2. You'll see the status page with connection information
3. Click on the client link to open the web client
4. The server URL should be automatically filled in
5. Click Connect and start chatting!

You can share the URL with anyone to let them join your chat.

## Local Testing

To test this version locally:

```bash
pip install -r requirements.txt
python start.py
```

Then open http://localhost:5000 in your browser. 

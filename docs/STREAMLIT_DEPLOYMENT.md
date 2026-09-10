# Streamlit Cloud Deployment Guide

## Problem
The app was showing: `groq.NotFoundError: This app has encountered an error...` due to missing `GROQ_API_KEY`.

## Solution Implemented

### 1. **Improved Error Handling**
Updated `ask.py` and `classify.py` with better error handling in `_get_groq_client()`:
- Changed from `.get()` to direct indexing for clearer error detection
- Better exception handling for missing keys
- Clearer error message pointing to all 3 configuration options

### 2. **Streamlit Cloud Setup** (PRIMARY METHOD)
This is required to run on Streamlit Cloud:

1. Go to [share.streamlit.io](https://share.streamlit.io)
2. Find your SecondSelf app in the app list
3. Click the **"Manage app"** button (⋮ menu in lower right)
4. Select **"Settings"** tab
5. Scroll to **"Secrets"** section
6. Add your Groq API key:
   ```toml
   GROQ_API_KEY = "gsk_xxxxxxxxxxxxxxxxxxxx"
   ```
7. Click **"Save"** and the app will auto-redeploy

### 3. **Local Development Setup**
Create `.streamlit/secrets.toml` in your project root:
```toml
GROQ_API_KEY = "your-api-key-here"
```

This file is already:
- Created in `.streamlit/secrets.toml`
- Ignored in `.gitignore` to prevent accidental commits

### 4. **Getting Your Groq API Key**
1. Go to [console.groq.com/keys](https://console.groq.com/keys)
2. Log in with your Groq account
3. Create a new API key
4. Copy the key (looks like: `gsk_xxxxxxxxxxxxxxxxxxxx`)

## API Key Priority (in order):
1. Environment variable: `GROQ_API_KEY` (system env)
2. `.env` file: `GROQ_API_KEY=...` (local development)
3. Streamlit Secrets: `GROQ_API_KEY` (Streamlit Cloud dashboard)

## Testing the Fix

### Local Testing
```bash
# Set environment variable (Windows)
$env:GROQ_API_KEY = "your-api-key"

# Or use .env file with python-dotenv
streamlit run app.py
```

### Streamlit Cloud Testing
1. Add secret via dashboard
2. Deploy/redeploy the app
3. Check logs: Click "Manage app" → "View logs"

## Troubleshooting

### Still getting "GROQ_API_KEY not set" error?
- [ ] Verify the secret is added in Streamlit Cloud dashboard
- [ ] Wait 30 seconds after adding secret for deploy to complete
- [ ] Check app logs for full error message
- [ ] Try manual reboot: Manage app → Reboot app

### API returns 401/403 errors?
- [ ] Verify API key is correct at [console.groq.com](https://console.groq.com/keys)
- [ ] Check API key hasn't expired or been revoked
- [ ] Ensure no extra spaces in the key

### Still failing after adding secret?
- [ ] Try removing the secret and re-adding it
- [ ] Restart the app via dashboard
- [ ] Check if `.env` file is interfering locally

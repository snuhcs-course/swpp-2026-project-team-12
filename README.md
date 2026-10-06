# 토닥 (Talk Dock)
AI-Powered Family Communication Manager (SNU SWPP 2026)

A mobile app for Korean families to share photos and updates with older adults, listen to AI-adapted messages, send voice replies, and review summaries.

## Structure

```text
client/                 Android app (placeholder)
backend/
  configs/              Django settings and API routes
  apps/accounts/        Account registration and authentication
  apps/families/        Family room and membership models
  apps/{posts,replies,digests}/  Feature TODOs
  integrations/ai/      AI integration TODOs
  developer/            Developer tools and sample data TODOs
  media/                Image storage (placeholder)
```

## Quick Start

From the repository root, install the backend dependencies (Python 3.11+):
```bash
python -m pip install -r backend/requirements.txt
cp .env.example .env
```
The server reads process environment variables in `.env`. 

```bash
python backend/manage.py migrate
python backend/manage.py runserver 127.0.0.1:8000
```

## Iteration 1 - TODO

## Iteration 1 - Limitations


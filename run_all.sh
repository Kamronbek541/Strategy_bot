#!/bin/bash

# Get current directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo "🚀 Starting Strategy Bot System..."

# Open Server (WebApp)
osascript -e "tell application \"Terminal\" to do script \"cd '$DIR' && python3 server.py\""

# Open Telegram Bot
osascript -e "tell application \"Terminal\" to do script \"cd '$DIR' && python3 bot.py\""

# Open Background Worker
osascript -e "tell application \"Terminal\" to do script \"cd '$DIR' && python3 worker.py\""

echo "✅ All services started in separate windows."

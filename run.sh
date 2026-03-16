#!/usr/bin/with-contenv bashio

# Read configuration from Home Assistant add-on options
DISCORD_TOKEN=$(bashio::config 'discord_token')
DISCORD_GUILD_ID=$(bashio::config 'discord_guild_id' '')
ADMIN_ROLE_NAME=$(bashio::config 'admin_role_name' 'Buchclub-Admin')

export DISCORD_TOKEN
export DISCORD_GUILD_ID
export ADMIN_ROLE_NAME

bashio::log.info "Starte Buchclub Discord Bot..."

exec python3 /app/bot.py

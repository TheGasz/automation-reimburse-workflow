/**
 * PM2 Production Deployment Configuration for KlaimKilat AI (VPS Deployment)
 * Usage: pm2 start ecosystem.config.js --env production
 */
module.exports = {
  apps: [
    {
      name: "klaimkilat-api",
      script: "uvicorn",
      args: "app.main:app --host 0.0.0.0 --port 8000 --workers 2",
      interpreter: "python3",
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: "512M",
      env: {
        APP_ENV: "development",
        DEBUG: "true",
      },
      env_production: {
        APP_ENV: "production",
        DEBUG: "false",
      },
    },
    {
      name: "klaimkilat-worker",
      script: "-m",
      args: "app.services.queue_worker",
      interpreter: "python3",
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: "512M",
      env: {
        APP_ENV: "development",
      },
      env_production: {
        APP_ENV: "production",
      },
    },
  ],
};

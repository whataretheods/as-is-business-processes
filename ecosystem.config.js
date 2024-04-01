module.exports = {
  apps: [{
    name: 'backend',
    script: 'app.py',
    interpreter: '/root/businessProcesses/as-is-business-processes/backend/venv/bin/python',
    watch: true,
    env: {
      NODE_ENV: 'development',
      // Other environment variables
    }
  }]
};

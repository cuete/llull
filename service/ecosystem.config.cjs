module.exports = {
  apps: [
    {
      name: "llull-api",
      script: "C:\\workspace\\repos\\llull\\service\\.venv\\Scripts\\uvicorn.exe",
      args: [
        "app.main:app",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--loop", "asyncio",
        "--ssl-certfile", "../.certs/echeverria.tail013d9a.ts.net.crt",
        "--ssl-keyfile", "../.certs/echeverria.tail013d9a.ts.net.key",
      ],
      cwd: "C:\\workspace\\repos\\llull\\service",
      interpreter: "none",
      restart_delay: 3000,
    }
  ]
};

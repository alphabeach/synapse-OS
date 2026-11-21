"""One-command boot: python run.py

HOST/PORT come from the environment so the same command runs locally
(0.0.0.0:8770) and on Render/Railway/Fly without a code change.
"""
import os

import uvicorn

from app import db


def main():
    db.init_db()
    uvicorn.run(
        "app.server:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8770")),
        workers=1,
    )


if __name__ == "__main__":
    main()

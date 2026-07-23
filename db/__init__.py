#!/usr/bin/env python3
"""
Job Agent Database Layer — SQLite persistence for jobs, tasks, apply_logs, models.

Usage:
  from db import get_db, init_db
  init_db()  # call once at startup
  db = get_db()
  db.add_job({"title": "...", "company": "..."})
"""

from .database import JobDB, get_db, init_db

__all__ = ["JobDB", "get_db", "init_db"]

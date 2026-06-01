"""SQLModel tables for the platform.

Populated in Chunk 1 (agents) and Chunk 3 (workflows, messages, runs, memory).
This module is imported by db.init_db() so every model registers on
SQLModel.metadata before create_all().
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    name = Column(String, nullable=True)
    plan = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Monitor(Base):
    __tablename__ = "monitors"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    url = Column(String, nullable=False)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class CheckResult(Base):
    __tablename__ = "check_results"
    id = Column(Integer, primary_key=True)
    monitor_id = Column(Integer, ForeignKey("monitors.id"))
    status_code = Column(Integer)
    response_time = Column(Float)
    is_up = Column(Boolean)
    checked_at = Column(DateTime, default=datetime.utcnow)

class Incident(Base):
    __tablename__ = "incidents"
    id = Column(Integer, primary_key=True)
    monitor_id = Column(Integer, ForeignKey("monitors.id"))
    started_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    is_resolved = Column(Boolean, default=False)
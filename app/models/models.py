from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey, Text, Date, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    plan = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    email_verified = Column(Boolean, default=False, nullable=False)
    email_canonical = Column(String, nullable=True, index=True)  # used to spot duplicate inboxes
    stripe_customer_id = Column(String, nullable=True, index=True)
    stripe_subscription_id = Column(String, nullable=True)
    password_set = Column(Boolean, default=True, nullable=False)   # False for email-only sign-ups
    email_alerts = Column(Boolean, default=True, nullable=False)   # down/up, hack and SSL emails
    monthly_reports = Column(Boolean, default=True, nullable=False)
    status_slug = Column(String, nullable=True, unique=True, index=True)
    timezone = Column(String, nullable=False, default="America/Vancouver")   # times in emails and dashboard   # hard-to-guess public status page address

class Monitor(Base):
    __tablename__ = "monitors"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    url = Column(String, nullable=False)     # website address, or the server's host name for port checks
    name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    kind = Column(String, nullable=False, default="website")   # website | port | heartbeat
    port = Column(Integer, nullable=True)                      # port checks only
    heartbeat_token = Column(String, nullable=True, unique=True, index=True)
    heartbeat_minutes = Column(Integer, nullable=True)         # how often the job should check in
    last_ping_at = Column(DateTime, nullable=True)

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

class DefacementWatch(Base):
    """Defacement monitoring settings and the 'known good' snapshot for one monitor."""
    __tablename__ = "defacement_watches"
    id = Column(Integer, primary_key=True)
    monitor_id = Column(Integer, ForeignKey("monitors.id"), unique=True, nullable=False)
    enabled = Column(Boolean, default=True)
    status = Column(String, default="learning")   # learning | ok | changed | suspicious | error
    baseline = Column(Text, nullable=True)         # JSON snapshot of the known-good page
    baseline_set_at = Column(DateTime, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    last_findings = Column(Text, nullable=True)    # JSON list of findings from the latest scan
    last_error = Column(String, nullable=True)
    last_alert_key = Column(String, nullable=True) # stops the same problem alerting twice


class DefacementEvent(Base):
    """A history entry each time the page was found changed or suspicious."""
    __tablename__ = "defacement_events"
    id = Column(Integer, primary_key=True)
    monitor_id = Column(Integer, ForeignKey("monitors.id"), nullable=False)
    detected_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String)                        # changed | suspicious
    findings = Column(Text)                        # JSON list
    resolved_at = Column(DateTime, nullable=True)
    resolution = Column(String, nullable=True)     # approved | reverted


class SslAlertState(Base):
    """Remembers which SSL reminder was last sent for a monitor, so each one is sent once."""
    __tablename__ = "ssl_alert_states"
    id = Column(Integer, primary_key=True)
    monitor_id = Column(Integer, ForeignKey("monitors.id"), unique=True, nullable=False)
    expiry_date = Column(String, nullable=True)       # certificate expiry the reminders refer to
    last_threshold = Column(Integer, nullable=True)   # e.g. 30, 14, 7, 3, 1, 0
    last_checked_at = Column(DateTime, nullable=True)



class DailySummary(Base):
    """One row per website per day: kept for the plan's full history after detailed checks are tidied away."""
    __tablename__ = "daily_summaries"
    __table_args__ = (UniqueConstraint("monitor_id", "day", name="uq_daily_monitor_day"),)
    id = Column(Integer, primary_key=True)
    monitor_id = Column(Integer, ForeignKey("monitors.id"), nullable=False, index=True)
    day = Column(Date, nullable=False)
    checks = Column(Integer, default=0)
    up_checks = Column(Integer, default=0)
    avg_response = Column(Float, nullable=True)
    max_response = Column(Float, nullable=True)


class DomainState(Base):
    """When each website's domain name registration runs out, and which reminder was last sent."""
    __tablename__ = "domain_states"
    id = Column(Integer, primary_key=True)
    monitor_id = Column(Integer, ForeignKey("monitors.id"), unique=True, nullable=False)
    domain = Column(String, nullable=True)
    expiry_date = Column(DateTime, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    last_threshold = Column(Integer, nullable=True)

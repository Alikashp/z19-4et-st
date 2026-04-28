from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, DateTime, Text, Float, BigInteger
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    balance_generations = Column(Integer, default=0)
    selected_language = Column(String(50), default="ru")


class Generation(Base):
    __tablename__ = "generations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    material_type = Column(String(50))   # report, abstract, presentation, sources
    input_type = Column(String(50))      # topic, text, document
    topic = Column(Text, nullable=True)
    level = Column(String(50), nullable=True)
    volume = Column(String(50), nullable=True)
    style = Column(String(50), nullable=True)
    source_format = Column(String(50), nullable=True)
    status = Column(String(50), default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    result_file_path = Column(String(500), nullable=True)


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    provider = Column(String(50))
    tariff_name = Column(String(100))
    amount = Column(Float)
    generations_count = Column(Integer)
    payment_id = Column(String(255), nullable=True)
    payment_url = Column(String(1000), nullable=True)
    status = Column(String(50), default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)

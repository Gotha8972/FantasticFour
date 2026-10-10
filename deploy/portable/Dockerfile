FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt requirements-portable.txt ./
RUN pip install --no-cache-dir -r requirements-portable.txt && useradd --uid 10001 --create-home agent && mkdir /data && chown agent /data
COPY chaosmind ./chaosmind
COPY profiles ./profiles
USER 10001
ENV CHAOSMIND_DATA=/data CHAOSMIND_PROFILES=/app/profiles
EXPOSE 8080
CMD ["uvicorn", "chaosmind.portable.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]

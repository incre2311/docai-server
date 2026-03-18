FROM jrottenberg/ffmpeg:4.4-alpine

RUN apk add --no-cache python3 py3-pip
RUN pip3 install flask flask-cors requests

WORKDIR /app
COPY . .

EXPOSE 8080
CMD ["python3", "main.py"]


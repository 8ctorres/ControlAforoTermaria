FROM python:3.12.7

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY aforo_termaria.py ./

CMD ["python", "aforo_termaria.py"]

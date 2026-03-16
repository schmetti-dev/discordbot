ARG BUILD_FROM
FROM $BUILD_FROM

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy bot source
COPY . .

# Make entrypoint executable
RUN chmod a+x /app/run.sh

CMD ["/app/run.sh"]

# -- Stage 1: Build the SvelteKit frontend --
FROM node:20-slim AS frontend

WORKDIR /app/frontend
COPY terminals/frontend/package.json terminals/frontend/package-lock.json ./
RUN npm ci
COPY terminals/frontend/ .
RUN npm run build

# -- Stage 2: Python application --
FROM python:3.12-slim

WORKDIR /app

COPY . .
# Copy built frontend assets from stage 1
COPY --from=frontend /app/frontend/build ./terminals/frontend/build

RUN pip install --no-cache-dir .

EXPOSE 3000

ENTRYPOINT ["terminals"]
CMD ["serve"]

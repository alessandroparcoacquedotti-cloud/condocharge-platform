FROM node:20-alpine

WORKDIR /app

ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ARG VITE_DEFAULT_CONDOMINIUM_NAME
ENV VITE_DEFAULT_CONDOMINIUM_NAME=$VITE_DEFAULT_CONDOMINIUM_NAME

COPY package.json /app/package.json
COPY package-lock.json /app/package-lock.json
RUN npm ci

COPY . /app

RUN echo "===== VITE CONFIG =====" && cat /app/vite.config.ts
RUN npm run build

ENV PORT=4173

EXPOSE 4173

CMD ["sh", "-c", "npx vite preview --host 0.0.0.0 --port $PORT"]

FROM node:20-alpine

WORKDIR /app

COPY package.json /app/package.json
COPY package-lock.json /app/package-lock.json
RUN npm ci

COPY . /app

RUN npm run build

ENV PORT=4173

EXPOSE 4173

CMD ["sh", "-c", "npx vite preview --host 0.0.0.0 --port $PORT"]

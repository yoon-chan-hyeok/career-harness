FROM node:22-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ENV BACKEND_URL=http://backend:8000
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build && cp -r .next/static .next/standalone/.next/static
ENV HOSTNAME=0.0.0.0
ENV PORT=3000
CMD ["node", ".next/standalone/server.js"]

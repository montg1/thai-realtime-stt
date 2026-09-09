# สร้าง static ด้วย node แล้วเสิร์ฟด้วย nginx — image สุดท้ายไม่มี node ติดไปด้วย
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
# SPA มีหน้าเดียว ทุก path ต้องตกมาที่ index.html ไม่งั้นรีเฟรชแล้ว 404
RUN printf 'server {\n\
  listen 80;\n\
  root /usr/share/nginx/html;\n\
  location / { try_files $uri $uri/ /index.html; }\n\
}\n' > /etc/nginx/conf.d/default.conf

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // 개발 서버는 기본적으로 localhost 외 origin의 요청을 403으로 막는다.
  // 휴대폰에서 Tailscale 주소로 접속하면 JS 청크가 전부 막혀 화면이 동작하지 않으므로 허용해 준다.
  allowedDevOrigins: [
    "desktop-sqi0657.tailc09694.ts.net",
    "*.ts.net",
    "100.70.249.73",
  ],
};

export default nextConfig;

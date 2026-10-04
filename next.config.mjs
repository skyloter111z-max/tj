/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // `npm run export`: 정적 파일로 뽑아 안드로이드·아이폰 앱 안에 넣는다(android/, ios/).
  // 앱은 서버 없이 이 파일들을 띄우고, 결제 알림은 브리지로 받는다.
  ...(process.env.SUBMOA_EXPORT ? { output: "export" } : {}),
};
export default nextConfig;

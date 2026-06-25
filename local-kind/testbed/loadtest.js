// loadtest.js — k6 bắn tải HTTP vào web service carserv qua HAProxy (localhost:30080)
// theo dạng SÓNG (ramp up -> đỉnh -> ramp down -> lặp). Dùng để có traffic thật minh hoạ
// + biểu đồ request trên trang HAProxy stats (localhost:30084).
//
// LƯU Ý: carserv là app TĨNH -> tải này gần như KHÔNG sinh CPU, nên KHÔNG dùng để điều
// khiển scaling. Tín hiệu điều khiển scale đến từ inject_testbed.py (testbed_cpu_usage).
// k6 ở đây phục vụ phần "sinh tải" trong báo cáo và để hệ thống có lưu lượng thật.
//
// Chạy:  BASE_URL=http://localhost:30080 k6 run loadtest.js
import http from "k6/http";
import { sleep, check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://localhost:30080";

export const options = {
  scenarios: {
    wave: {
      executor: "ramping-vus",
      startVUs: 0,
      // Một chu kỳ sóng ~10 phút; lặp lại để khớp thời lượng quay demo.
      stages: [
        { duration: "2m", target: 50 },   // tăng dần
        { duration: "1m", target: 150 },  // lên đỉnh
        { duration: "2m", target: 150 },  // giữ đỉnh
        { duration: "2m", target: 30 },   // giảm
        { duration: "1m", target: 0 },    // nghỉ
        { duration: "2m", target: 80 },   // sóng thứ hai
        { duration: "2m", target: 0 },
      ],
      gracefulRampDown: "10s",
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.05"],   // <5% request lỗi
  },
};

export default function () {
  const res = http.get(`${BASE_URL}/`);
  check(res, { "status is 200": (r) => r.status === 200 });
  sleep(1);
}

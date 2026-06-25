// calibrate.js — Bắn tải Ở MỘT MỨC RPS CỐ ĐỊNH để đo CPU tương ứng (hiệu chỉnh RPS->CPU).
// Chạy với 1 pod cố định (vòng hở) rồi đọc CPU từ Prometheus.
//
// Dùng:  RATE=20 DURATION=2m BASE_URL=http://localhost:30080 k6 run calibrate.js
//   - RATE     : số request/giây cố định
//   - DURATION : thời lượng (để CPU ổn định, nên >= 90s vì query CPU dùng rate[1m])
import http from "k6/http";

const RATE = parseInt(__ENV.RATE || "20");
const DUR  = __ENV.DURATION || "2m";

export const options = {
  scenarios: {
    constant: {
      executor: "constant-arrival-rate",
      rate: RATE,
      timeUnit: "1s",
      duration: DUR,
      preAllocatedVUs: 50,
      maxVUs: 1000,
    },
  },
};

export default function () {
  http.get(__ENV.BASE_URL || "http://localhost:30080");
}

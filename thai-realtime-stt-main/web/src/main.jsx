import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

// และ SpeakerHandler ฝั่งเซิร์ฟเวอร์ถูกสร้างสองชุดโดยไม่จำเป็น
createRoot(document.getElementById("root")).render(<App />);

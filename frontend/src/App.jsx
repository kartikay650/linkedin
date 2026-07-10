import Dashboard from "./pages/Dashboard.jsx";
import AuthGate from "./AuthGate.jsx";

export default function App() {
  return (
    <AuthGate>
      <Dashboard />
    </AuthGate>
  );
}

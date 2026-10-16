import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AuthGate } from './components/AuthGate';
import { Layout } from './components/layout/Layout';
import { Dashboard } from './pages/Dashboard';
import { Requests } from './pages/Requests';
import { Sessions } from './pages/Sessions';
import { Honeypots } from './pages/Honeypots';
import { Sensors } from './pages/Sensors';
import { Alerts } from './pages/Alerts';
import { Rules } from './pages/Rules';
import { TokenExhaust } from './pages/TokenExhaust';
import { Scenarios } from './pages/Scenarios';
import { Blocks } from './pages/Blocks';

export default function App() {
  return (
    <BrowserRouter>
      <AuthGate>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/requests" element={<Requests />} />
            <Route path="/sessions" element={<Sessions />} />
            <Route path="/token-exhaust" element={<TokenExhaust />} />
            <Route path="/scenarios" element={<Scenarios />} />
            <Route path="/honeypots" element={<Honeypots />} />
            <Route path="/sensors" element={<Sensors />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/blocks" element={<Blocks />} />
            <Route path="/rules" element={<Rules />} />
          </Route>
        </Routes>
      </AuthGate>
    </BrowserRouter>
  );
}

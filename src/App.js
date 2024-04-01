import React, {useState } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import Login from './components/Login';
import FileUpload from './components/FileUpload';


const App = () => {
  const token = localStorage.getItem('token');
  const [isOpen, setIsOpen] = useState(false);

  return (
    <Router>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route 
          path="/upload" 
          element={token ? <FileUpload isOpen={isOpen} setIsOpen={setIsOpen} /> : <Navigate to="/login" replace />} 
        />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </Router>
  );
};

export default App;
/*
const PrivateRoute = ({ element: Element, ...rest }) => {
  const token = localStorage.getItem('token');

  return token ? (
    <Route {...rest} element={<Element />} />
  ) : (
    <Navigate to="/login" replace />
  );
};

const App = () => {
  return (
    <Router>
      <Routes>
        <Route path="/login" element={<Login />} />
        <PrivateRoute path="/upload" element={FileUpload} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </Router>
  );
};

export default App;
*/

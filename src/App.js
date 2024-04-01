import React, {useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import Login from './components/Login';
import FileUpload from './components/FileUpload';
import Navigation from './components/Navigation';
import './App.css';

const App = () => {
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  useEffect(() => {
    // This effect runs once on mount to check authentication status
    const token = localStorage.getItem('token');
    setIsAuthenticated(!!token);
  }, []);

  return (
    <div className="app-container">
      <Router>
        {isAuthenticated && <div className="navigation"><Navigation /></div>}
        <div className="main-content">
          <Routes>
            <Route path="/login" element={<Login setAuthenticated={setIsAuthenticated} />} />
            <Route 
              path="/upload" 
              element={isAuthenticated ? <FileUpload /> : <Navigate to="/login" />} 
            />
            <Route path="*" element={<Navigate to={isAuthenticated ? "/upload" : "/login"} />} />
          </Routes>
        </div>
      </Router>
    </div>
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

import React from 'react';
import { useNavigate } from 'react-router-dom';

const Navigation = ({ setIsAuthenticated }) => {
  const navigate = useNavigate();

  const handleLogout = () => {
    localStorage.removeItem('token');
    setIsAuthenticated(false); /* updates authentication status to false when user logs out */
    navigate('/login');
  };

  return (
    <div className="sidebar">
      <div className="sidebar-links">
        <a href="#cleanup">Audantic Data Cleanup</a>
        <a href="#logs">User Logs</a>
        <a href="#manage">Manage Users</a>
        <a href="#download">Download Files</a>
      </div>
      <div className="logout-bottom" onClick={handleLogout}>Log Out</div>
    </div>
  );
};

export default Navigation;

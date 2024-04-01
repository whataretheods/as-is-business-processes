import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';

const Navigation = ({ isOpen, setIsOpen }) => {
  const navigate = useNavigate();

  const handleLogout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  return (
    <div className={`sidebar ${isOpen ? 'open' : ''}`}>
      <a href="#cleanup" onClick={() => setIsOpen(false)}>Audantic Data Cleanup</a>
      <a href="#logs" onClick={() => setIsOpen(false)}>User Logs</a>
      <a href="#manage" onClick={() => setIsOpen(false)}>Manage Users</a>
      <a href="#download" onClick={() => setIsOpen(false)}>Download Files</a>
      <div className="logout-bottom" onClick={handleLogout}>Log Out</div>
    </div>
  );
};

export default Navigation;

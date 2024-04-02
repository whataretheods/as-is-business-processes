import React, { useState } from 'react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';

const Login = ({ setAuthenticated }) => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      console.log('API URL:', process.env.REACT_APP_API_URL);
      const response = await axios.post(`${process.env.REACT_APP_API_URL}/login`, { username, password });
      const token = response.data.token;
      localStorage.setItem('token', token);
      setAuthenticated(true);
      navigate('/upload');
    } catch (error) {
      console.error('Login error:', error);
      setAuthenticated(false);
      if (error.response && error.response.status === 401) {
        alert('Invalid username or password. Please try again.');
      } else {
        alert('Login failed. Please try again.');
      }
    }
  };

  return (
    <div className="login-page">
      <h2>Welcome, please log in</h2>
      <div className="login-container">
        <form onSubmit={handleSubmit} className="login-form">
          <div className="form-group">
            <label htmlFor="username">Username:</label>
            <input
              type="username"
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>
          <div className="form-group">
            <label htmlFor="password">Password:</label>
            <input
              type="password"
              id="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <button type="submit" className="styled-button">Login</button>
        </form>
      </div>
    </div>
  );
};

export default Login;

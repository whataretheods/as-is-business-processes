import React from 'react';
import axios from 'axios';

const FileDownload = () => {
  const handleDownload = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await axios.get('http://localhost:5001/download_uniques_list', {
        headers: {
          'Authorization': `Bearer ${token}`
        },
        responseType: 'blob'
      });

      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', 'uniques_list.csv');
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (error) {
      console.error('Error downloading uniques list:', error);
      alert('An error occurred while downloading the uniques list.');
    }
  };

  return (
    <div>
      <button onClick={handleDownload}>Download Uniques List</button>
    </div>
  );
};

export default FileDownload;
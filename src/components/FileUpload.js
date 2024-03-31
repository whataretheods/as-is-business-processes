import React, { useState, useRef } from 'react';
import axios from 'axios';
import Navigation from './Navigation';
import FileDownload from './FileDownload';

const FileUpload = () => {
  const [files, setFiles] = useState([]);
  const [sourceName, setSourceName] = useState('');
  const [listName, setListName] = useState('');
  const [result, setResult] = useState(null);
  const dropzoneRef = useRef(null);

  const handleFileChange = (e) => {
    setFiles(Array.from(e.target.files));
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = 'copy';
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    const droppedFiles = Array.from(e.dataTransfer.files);
    setFiles((prevFiles) => [...prevFiles, ...droppedFiles]);;
  };
  
  const handleRemoveFile = (index) => {
    setFiles((currentFiles) => currentFiles.filter((_, i) => i !== index));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
  
    const formData = new FormData();
    files.forEach((file) => {
      formData.append('files', file);
    });
    formData.append('source_name', sourceName);
    formData.append('list_name', listName);
  
    try {
      const token = localStorage.getItem('token');
      const response = await axios.post(`${process.env.REACT_APP_API_URL}/process_spreadsheets`, formData, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      setResult(response.data);
    } catch (error) {
      console.error('Error processing spreadsheets:', error);
      if (error.response) {
        // The request was made and the server responded with a status code
        // that falls out of the range of 2xx
        console.log('Response data:', error.response.data);
        console.log('Response status:', error.response.status);
        alert(`Error processing spreadsheets: ${error.response.data.message}`);
      } else if (error.request) {
        // The request was made but no response was received
        console.log('No response received:', error.request);
        alert('No response received from the server. Please try again.');
      } else {
        // Something else happened in making the request
        console.log('Error:', error.message);
        alert('An error occurred. Please try again.');
      }
    }
  };

  return (
    <div>
      <Navigation />
      <form onSubmit={handleSubmit}>
          <div
            ref={dropzoneRef}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
            style={{ border: '2px dashed #ccc', padding: '20px', textAlign: 'center' }}
          >
          <p>Drag and drop files here or click to select files</p>
          <input type="file" multiple onChange={handleFileChange} />
          <div>
            {/* Display file names here */}
            {files.map((file, index) => (
              <div key={index}>
                {file.name}
                <button type="button" onClick={() => handleRemoveFile(index)}>Remove</button>
              </div>
            ))}
          </div>
        </div>

        <div>
          <label htmlFor="sourceName">Source Name:</label>
          <input
            type="text"
            id="sourceName"
            value={sourceName}
            onChange={(e) => setSourceName(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="listName">List Name:</label>
          <input
            type="text"
            id="listName"
            value={listName}
            onChange={(e) => setListName(e.target.value)}
          />
        </div>
        <button type="submit">Process Spreadsheets</button>
      </form>
      {result && (
        <div>
          <h3>Processing Result:</h3>
          <p>Unique Count: {result.unique_count}</p>
          <p>Message: {result.message}</p>
          <FileDownload />
        </div>
      )}
    </div>
  );
};

export default FileUpload;

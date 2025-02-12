// src/components/FileUpload.js
import React, { useState } from 'react';
import axios from 'axios';
import FileDownload from './FileDownload';

const FileUpload = () => {
  const [files, setFiles] = useState([]);
  const [sourceName, setSourceName] = useState('');
  const [listName, setListName] = useState('');
  const [result, setResult] = useState(null);
  const [skiptracedDate, setSkiptracedDate] = useState('');
  const [skiptracedResult, setSkiptracedResult] = useState(null);
  const [filesToUpload, setFilesToUpload] = useState([]);
  const [fileDisplayInfo, setFileDisplayInfo] = useState([]);

  const handleFileChange = (e) => {
    const selectedFiles = Array.from(e.target.files);
    setFiles(selectedFiles);
    handleFileProcessing(selectedFiles);
  };

  const handleFileProcessing = (files) => {
    const filePromises = files.map(file =>
      new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (readEvent) => {
          const contents = readEvent.target.result;
          const rows = contents.split('\n').length - 1;
          resolve({ fileName: file.name, rowCount: rows });
        };
        reader.onerror = reject;
        reader.readAsText(file);
      })
    );
    Promise.all(filePromises)
      .then(fileInfos => {
        setFilesToUpload(prev => [...prev, ...files]);
        setFileDisplayInfo(prev => [...prev, ...fileInfos]);
      })
      .catch(error => console.error('Error processing files:', error));
  };

  const handleSkiptracedFileChange = (e) => {
    const selectedFiles = Array.from(e.target.files);
    handleFileProcessing(selectedFiles);
  };

  const handleSkiptracedDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = 'copy';
  };

  const handleSkiptraceDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    const droppedFiles = Array.from(e.dataTransfer.files);
    handleFileProcessing(droppedFiles);
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
    setFiles(prev => [...prev, ...droppedFiles]);
    handleFileProcessing(droppedFiles);
  };

  const handleRemoveFile = (index) => {
    setFiles(prev => prev.filter((_, i) => i !== index));
    setFilesToUpload(prev => prev.filter((_, i) => i !== index));
    setFileDisplayInfo(prev => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const formData = new FormData();
    files.forEach(file => formData.append('files', file));
    formData.append('source_name', sourceName);
    formData.append('list_name', listName);
    try {
      const token = localStorage.getItem('token');
      const response = await axios.post(`${process.env.REACT_APP_API_URL}/process_spreadsheets`, formData, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      setResult(response.data);
    } catch (error) {
      console.error('Error processing spreadsheets:', error);
      if (error.response) {
        console.log('Response data:', error.response.data);
        alert(`Error processing spreadsheets: ${error.response.data.message}`);
      } else {
        alert('An error occurred. Please try again.');
      }
    }
  };

  const handleSkiptracedSubmit = async () => {
    const formData = new FormData();
    filesToUpload.forEach(file => formData.append('files', file));
    formData.append('skip_traced_date', skiptracedDate);
    try {
      const token = localStorage.getItem('token');
      const response = await axios.post(`${process.env.REACT_APP_API_URL}/process_skiptraced`, formData, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      setSkiptracedResult(response.data);
    } catch (error) {
      console.error('Error processing skiptraced data:', error);
      alert('An error occurred while processing the skiptraced data.');
    }
  };

  return (
    <div className="file-upload-container">
      <div className="main-content">
        <div className="step-container">
          <h2 className="step-title">Step 1: Format Data and Get Unique Rows</h2>
          <div onDragOver={handleDragOver} onDrop={handleDrop} className="dropzone">
            <label className="styled-input"><p>Drag and Drop files here</p></label>
            <input type="file" multiple onChange={handleFileChange} />
            <div className="file-list">
              {files.map((file, index) => (
                <div key={index} className="file-item">
                  {file.name}
                  <button onClick={() => handleRemoveFile(index)} className="styled-button">x</button>
                </div>
              ))}
            </div>
          </div>
          <div className="inputs-container">
            <input
              type="text"
              placeholder="Source Name..."
              value={sourceName}
              onChange={(e) => setSourceName(e.target.value)}
              className="styled-input"
            />
            <input
              type="text"
              placeholder="List Name..."
              value={listName}
              onChange={(e) => setListName(e.target.value)}
              className="styled-input"
            />
            <button onClick={handleSubmit} className="styled-button">Process Spreadsheets</button>
            {result && (
              <div className="result-container">
                <h3>Processing Result:</h3>
                <p>Unique Count: {result.unique_count}</p>
                <p>Message: {result.message}</p>
                <FileDownload />
              </div>
            )}
          </div>
        </div>
        <div className="step-container">
          <h2 className="step-title">Step 2: Format Skiptraced Data and Add to Master List</h2>
          <div onDragOver={handleSkiptracedDragOver} onDrop={handleSkiptraceDrop} className="dropzone">
            <label className="styled-input"><p>Drag and Drop files here</p></label>
            <input type="file" multiple onChange={handleSkiptracedFileChange} />
            <div className="file-list">
              {fileDisplayInfo.map((info, index) => (
                <div key={index} className="file-item">
                  {info.fileName} - Rows: {info.rowCount}
                  <button onClick={() => handleRemoveFile(index)} className="styled-button">x</button>
                </div>
              ))}
            </div>
          </div>
          <div className="inputs-container">
            <input
              type="text"
              placeholder="Skiptraced Date (MM/DD/YYYY)..."
              value={skiptracedDate}
              onChange={(e) => setSkiptracedDate(e.target.value)}
              className="styled-input"
            />
            <button onClick={handleSkiptracedSubmit} className="styled-button">Process Skiptraced Data</button>
            {skiptracedResult && (
              <div className="result-container">
                <h3>Processing Result:</h3>
                <p>Standardization: {skiptracedResult.standardization}</p>
                <p>Merge Status: {skiptracedResult.mergeStatus}</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default FileUpload;

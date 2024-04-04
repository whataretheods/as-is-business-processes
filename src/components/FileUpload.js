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
  const [skiptracedFiles, setSkiptracedFiles] = useState([]);
  const [skiptracedDate, setSkiptracedDate] = useState('');
  const [skiptracedResult, setSkiptracedResult] = useState(null);

  const handleFileChange = (e) => {
    setFiles(Array.from(e.target.files));
  };

  const handleLogout = () => {
    // Remove the token or user session
    localStorage.removeItem('token');
    // Redirect to the login page or perform other cleanup
  };


  // Count the number of rows in each file
  const countRows = async (file): Promise<number> => {
    return new Promise((resolve, reject) => {
      try {
        const reader = new FileReader();
        reader.onload = (event) => {
          const contents = event.target.result;
          const rowCount = contents.split('\n');
          resolve(rowCount.length);
        };
          
        reader.readAsText(file);
      } catch (error) {
        reject(error);
      }
    });
  };

  const handleSkiptraceDragOver = (second) => {
    second.preventDefault();
    second.stopPropagation();
    second.dataTransfer.dropEffect = 'copy';
  };

  const handleSkiptraceDrop = async (event) => {
    event.preventDefault();
    event.stopPropagation();
    const droppedFiles = Array.from(event.dataTransfer.files);  
    // Process each file to include rowCount and fileName similar to handleSkiptracedFileChange
    const filePromises = droppedFiles.map(file => {
        return new Promise((resolve, reject) => { 
            const reader = new FileReader();
            reader.onload = (readEvent) => {
                const contents = readEvent.target.result;
                const rows = contents.split('\n').length - 1; // Ignore header row
                resolve({ file, rowCount: rows, fileName: file.name });
            };
            reader.onerror = reject;
            reader.readAsText(file);
        });
    });

    Promise.all(filePromises)
        .then(updatedFiles => {
            setSkiptracedFiles(prevFiles => [...prevFiles, ...updatedFiles]);
        })
        .catch(error => console.error('Error reading files:', error));
  };



  const handleSkiptracedFileChange = async (second) => {
    const files = Array.from(second.target.files);
    const filePromises = files.map((file) => {
      return new Promise((resolve, reject) => { 
        const reader = new FileReader();
        reader.onload = (event) => {
          const contents = event.target.result;
          const rows = contents.split('\n').length - 1; // Ignore header row
         
          resolve({ file, rowCount: rows, fileName: file.name });
        };
        reader.onerror = reject;
        reader.readAsText(file);
      });
    }); 

    Promise.all(filePromises)
      .then(updatedFiles => {
        setSkiptracedFiles((prevFiles) => [...prevFiles, ...updatedFiles]);
      })
      .catch(error => console.error('Error reading files:', error));
  };

  const handleRemoveSkiptracedFile = (index) => {
    setSkiptracedFiles((currentFiles) => currentFiles.filter((_, i) => i !== index));
  };
 
  const handleSkiptracedSubmit = async (second) => {
    // Prepare the data to send to the backend
    const formData = new FormData();
    console.log(formData)
    console.log(skiptracedFiles);
    try {
      skiptracedFiles.forEach((file) => {
        formData.append('files', file);
      });
      formData.append('skip_traced_date', skiptracedDate);
    } catch (error) {
      console.error('Error:', error);
    }
    try {
      const token = localStorage.getItem('token');
      const response = await axios.post(`${process.env.REACT_APP_API_URL}/process_skiptraced`, formData, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      setSkiptracedResult(response.data);
    } catch (error) {
      console.error('Error processing skiptraced data:', error);
      alert('An error occurred while processing the skiptraced data.');
    }
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
    <div className="file-upload-container">
      <div className="main-content">
        <div className="step-container">
          <h2 className="step-title">Step 1: Format Data and Get Unique Rows</h2>
          <div
            onDragOver={handleDragOver}
            onDrop={handleDrop}
            className="dropzone"
          >
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
              id="sourceName"
              placeholder="Source Name..."
              value={sourceName}
              onChange={(e) => setSourceName(e.target.value)}
              className="styled-input"
            />
            <input
              type="text"
              id="listName"
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
                <FileDownload /> {/* This button will only appear if there is a result */}
              </div>
            )}
          </div>
        </div>
        <div className="step-container">
          <h2 className="step-title">Step 2: Format Skiptraced Data and Add to Master List</h2>
            <div onDragOver={handleSkiptraceDragOver} onDrop={handleSkiptraceDrop} className="dropzone">
            <label className="styled-input"><p>Drag and Drop files here</p></label>
            <input type="file" multiple onChange={handleSkiptracedFileChange} />
            <div className="file-list">
              {skiptracedFiles.map((file, index) => (
                <div key={index} className="file-item">
                  {file.fileName} - Rows: {file.rowCount}
                  <button onClick={() => handleRemoveSkiptracedFile(index)} className="styled-button">x</button>
                </div>
              ))}
            </div>
          </div>
            <div className="inputs-container">
              <input
                type="text"
                id="skiptracedDate"
                placeholder="Skiptraced Date (MM/DD/YYYY)..."
                value={skiptracedDate}
                onChange={(second) => setSkiptracedDate(second.target.value)}
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
}
export default FileUpload;

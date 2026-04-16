document.getElementById('grant-btn').addEventListener('click', async () => {
  const status = document.getElementById('status');
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    status.textContent = 'Microphone access granted!';
    status.style.color = 'green';
    // Stop the stream immediately
    stream.getTracks().forEach(track => track.stop());
  } catch (err) {
    status.textContent = 'Permission denied: ' + err.message;
    status.style.color = 'red';
  }
});
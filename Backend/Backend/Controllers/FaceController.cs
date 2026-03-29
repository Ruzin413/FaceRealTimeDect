using Microsoft.AspNetCore.Mvc;
using Backend.Models;
using Backend.Dbcontext;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;

namespace Backend.Controllers
{
    [Route("api/[controller]")]
    [ApiController]
    public class FaceController : ControllerBase
    {
        private readonly AppDbContext _context;
        private readonly HttpClient _httpClient;
        private readonly string _uploadPath;

        public FaceController(AppDbContext context, IHttpClientFactory httpClientFactory)
        {
            _context = context;
            _httpClient = httpClientFactory.CreateClient();
            _httpClient.BaseAddress = new Uri("http://localhost:8000/");
            _uploadPath = Path.Combine(Directory.GetCurrentDirectory(), "Uploads");
            if (!Directory.Exists(_uploadPath))
            {
                Directory.CreateDirectory(_uploadPath);
            }
        }

        [HttpPost("enroll")]
        public async Task<IActionResult> EnrollFace([FromForm] string name, IFormFile image)
        {
            if (string.IsNullOrEmpty(name))
            {
                return BadRequest("Name is required.");
            }

            if (image == null || image.Length == 0)
            {
                return BadRequest("Valid image is required.");
            }

            // 1. Save Image locally
            var fileName = $"{Guid.NewGuid()}_{image.FileName}";
            var filePath = Path.Combine(_uploadPath, fileName);

            using (var stream = new FileStream(filePath, FileMode.Create))
            {
                await image.CopyToAsync(stream);
            }

            // 2. Send image to Python Service to get the embedding
            string embeddingJson = null;
            try
            {
                using var multipartFormContent = new MultipartFormDataContent();
                
                // Read file stream again for sending
                using var imageStream = new FileStream(filePath, FileMode.Open, FileAccess.Read);
                var streamContent = new StreamContent(imageStream);
                streamContent.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue(image.ContentType);
                
                multipartFormContent.Add(streamContent, "file", image.FileName);

                var response = await _httpClient.PostAsync("extract_embedding", multipartFormContent);

                if (!response.IsSuccessStatusCode)
                {
                    var errorDetails = await response.Content.ReadAsStringAsync();
                    return StatusCode((int)response.StatusCode, $"AI Service Error: {errorDetails}");
                }

                var jsonResponse = await response.Content.ReadAsStringAsync();
                
                using var document = JsonDocument.Parse(jsonResponse);
                if (document.RootElement.TryGetProperty("embedding", out var embeddingElement))
                {
                    embeddingJson = embeddingElement.GetRawText();
                }
                else
                {
                    return StatusCode(500, "AI Service did not return 'embedding'.");
                }
            }
            catch (Exception ex)
            {
                return StatusCode(500, $"Failed to contact AI Service: {ex.Message}");
            }
            var user = new User
            {
                Name = name,
                Embedding = embeddingJson,
                ImagePath = fileName,
                CreatedAt = DateTime.UtcNow
            };
            _context.Users.Add(user);
            await _context.SaveChangesAsync();
            return Ok(new { Message = "Face Enrolled Successfully", UserId = user.Id, Name = user.Name });
        }
        [HttpGet("strangers")]
        public async Task<IActionResult> GetStrangers()
        {
            // Fetch from DB first
            var users = await _context.Users
                .OrderByDescending(u => u.CreatedAt)
                .ToListAsync();

            // Map in-memory
            var result = users.Select(u => new
            {
                u.Id,
                u.Name,
                u.CreatedAt,
                ImageUrl = !string.IsNullOrEmpty(u.ImagePath) 
                    ? $"http://localhost:5081/Uploads/{u.ImagePath}" 
                    : $"http://localhost:5081/Uploads/{u.Name.Replace(" ", "_")}.jpg"
            });

            return Ok(result);
        }

        [HttpDelete("{id}")]
        public async Task<IActionResult> DeleteUser(int id)
        {
            var user = await _context.Users.FindAsync(id);
            if (user == null)
            {
                return NotFound();
            }

            _context.Users.Remove(user);
            await _context.SaveChangesAsync();

            return Ok(new { Message = "User deleted successfully." });
        }

        [HttpPut("{id}")]
        public async Task<IActionResult> UpdateUser(int id, [FromBody] UserUpdateRequest request)
        {
            var user = await _context.Users.FindAsync(id);
            if (user == null)
            {
                return NotFound();
            }

            user.Name = request.Name;
            await _context.SaveChangesAsync();

            return Ok(new { Message = "User updated successfully." });
        }
    }

    public class UserUpdateRequest
    {
        public string Name { get; set; }
    }
}

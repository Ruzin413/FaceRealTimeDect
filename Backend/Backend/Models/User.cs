namespace Backend.Models
{
    public class User
    {
        public int Id { get; set; }
        public string Name { get; set; }
        public string Embedding { get; set; } // JSON list of 10 embeddings
        public string? ImagePath { get; set; } // Path to the saved face crop
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    }
}
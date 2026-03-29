using Backend.Models;
using Microsoft.EntityFrameworkCore;
using OpenCvSharp;

namespace Backend.Dbcontext
{
    public class AppDbContext : DbContext
    {
        public AppDbContext(DbContextOptions<AppDbContext> options) : base(options)
        {
        }

        public DbSet<User> Users { get; set; }
    }
}
